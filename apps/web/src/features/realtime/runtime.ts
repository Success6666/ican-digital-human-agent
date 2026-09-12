import type { AvatarSession } from '../../shared/api/types'
import { flushClientEvents, reportClientEvent, setTelemetryContext } from '../observability/clientReporter'
import { buildRealtimeConfig, controlFrame } from './protocol'
import { RealtimeEventGate } from './eventGate'
import { handleRealtimeEvent } from './events'
import { booleanCapability, isUnsupportedCapability } from './capabilities'
import { Pcm16PlaybackQueue } from './playback'
import { Pcm16Recorder, pcmFrameBytes } from './pcm16'
import { RealtimeTransport, nextId } from './transport'
import { decideAudioEnd } from './audioLifecycle'
import type { RealtimeAction, RealtimeClientConfig, RealtimeInboundEvent, RealtimeSessionOptions, RealtimeState } from './types'
import { hasAudioInput } from './types'

type Dispatch = (action: RealtimeAction) => void
type OptionsReader = () => RealtimeSessionOptions

type ActiveCapture = {
  transport: RealtimeTransport
  config: RealtimeClientConfig
  operation: number
}

type RecorderConfig = Pick<RealtimeClientConfig, 'sampleRate' | 'channels' | 'frameMs'>

/** Level above which a frame counts as speech rather than room noise. */
const SPEECH_LEVEL_THRESHOLD = 0.035

/**
 * How long to keep listening after the user goes quiet.
 *
 * A flat window is the single largest fixed delay in the voice loop, so it is
 * derived from how the turn actually ended instead of being a constant:
 * a loud, decisive finish is very unlikely to be followed by more words, while
 * a soft or faded finish may be a mid-sentence pause worth waiting through.
 * Values stay inside a band so the behaviour never becomes unpredictable.
 */
const SILENCE_WINDOW_MIN_MS = 320
const SILENCE_WINDOW_MAX_MS = 650
/** Below this trailing loudness the ending looks like a fade, not a finish. */
const QUIET_ENDING_LEVEL = 0.08

export function endOfTurnSilenceMs(peakLevel: number, trailingLevel: number): number {
  if (peakLevel >= 0.25 && trailingLevel < QUIET_ENDING_LEVEL) return SILENCE_WINDOW_MIN_MS
  if (peakLevel >= 0.25) return 380
  if (peakLevel >= 0.12) return 500
  return SILENCE_WINDOW_MAX_MS
}

/** Agent-facing runtime: owns utterance generations, audio and presentation state. */
export class RealtimeRuntime {
  readonly textSupported: boolean
  readonly supported: boolean
  private readonly sessionId?: string
  private readonly dispatch: Dispatch
  private readonly readOptions: OptionsReader
  private gate = new RealtimeEventGate()
  private config?: RealtimeClientConfig
  private transport?: RealtimeTransport
  private recorder?: Pcm16Recorder
  private recorderConfig?: RecorderConfig
  private activeCapture?: ActiveCapture
  private playback?: Pcm16PlaybackQueue
  private revision = 0
  private utteranceId?: string
  private runId?: string
  /**
   * Current run trace. Falls back to the connection id so capture events that
   * happen before a run exists still land on the realtime connection trace.
   */
  private traceId?: string
  private connectionId?: string
  private utteranceOpen = false
  private audioStarted = false
  private operation = 0
  private disposed = false
  private silenceTimer?: ReturnType<typeof setTimeout>
  private maxRecordingTimer?: ReturnType<typeof setTimeout>
  private speechDetected = false
  /** Highest level seen in the current breath so the end-of-turn wait can adapt. */
  private peakSpeechLevel = 0
  private trailingSpeechLevel = 0

  constructor(session: AvatarSession | null, dispatch: Dispatch, readOptions: OptionsReader) {
    this.sessionId = session?.sessionId
    this.textSupported = Boolean(session?.sessionId)
    this.supported = hasAudioInput(session)
    this.dispatch = dispatch
    this.readOptions = readOptions
  }

  mount(session: AvatarSession | null): void {
    if (!session?.sessionId || this.disposed) return
    this.config = buildRealtimeConfig(session.sessionId, session.clientParams)
    setTelemetryContext({ sessionId: session.sessionId })
    const config = this.config
    this.playback = this.createPlayback(config)
    this.transport = new RealtimeTransport(session.sessionId, config, {
      onState: (state) => this.handleTransportState(state),
      onReady: (event) => this.handleReady(event),
      onEvent: (event) => this.handleInbound(event),
      onError: (message) => this.dispatch({ type: 'error', message }),
    })
    this.transport.mount()
  }

  async dispose(): Promise<void> {
    if (this.disposed) return
    this.disposed = true
    ++this.operation
    await this.releaseRecorder()
    this.clearRecordingTimers()
    this.dispatch({ type: 'audio_level', level: 0 })
    this.playback?.interrupt()
    if (this.playback) await this.playback.close()
    await this.transport?.dispose()
    this.playback = undefined
    this.transport = undefined
  }

  get isRecording(): boolean { return Boolean(this.recorder?.isRecording) }

  async connect(): Promise<boolean> {
    if (this.disposed || !this.transport) return false
    return this.transport.connect()
  }
  async disconnect(): Promise<void> {
    ++this.operation
    const previousUtterance = this.utteranceId
    const previousRevision = this.revision
    await this.releaseRecorder()
    this.clearRecordingTimers()
    this.dispatch({ type: 'audio_level', level: 0 })
    if (this.audioStarted) this.sendAudioEnd(previousUtterance, previousRevision)
    this.playback?.interrupt()
    this.transport?.close()
    this.audioStarted = false
    this.utteranceOpen = false
    this.dispatch({ type: 'connection', state: 'closed' })
  }

  async interrupt(reason = 'client_interrupt'): Promise<void> {
    await this.cancelCurrent(reason, true)
  }
  async startRecording(): Promise<boolean> {
    if (this.disposed || !this.supported || !this.sessionId) {
      this.dispatch({ type: 'recording', state: 'unsupported', message: '当前仅支持文本实时链路' })
      return false
    }
    const transport = this.transport
    const config = this.config
    if (!transport || !config || !(await transport.connect())) return false
    if (config.codec !== 'pcm_s16le') {
      this.dispatch({ type: 'error', message: '当前实时通道返回了不支持的音频格式' })
      return false
    }
    await this.cancelCurrent('speech_start', true)
    const operation = ++this.operation
    const utteranceId = nextId('utt')
    const revision = ++this.revision
    this.utteranceId = utteranceId
    this.runId = undefined
    this.gate.reset(utteranceId, revision)
    this.utteranceOpen = true
    this.dispatch({ type: 'revision', utteranceId, revision })
    this.dispatch({ type: 'recording', state: 'requesting' })
    this.speechDetected = false
    this.peakSpeechLevel = 0
    this.trailingSpeechLevel = 0
    this.clearRecordingTimers()
    this.report('capture.permission_request', { utteranceId, revision })
    let audioStartSent = false
    let recorder: Pcm16Recorder | undefined
    try {
      recorder = await this.getRecorder(config)
      this.activeCapture = { transport, config, operation }
      audioStartSent = transport.send(controlFrame('audio_start', {
        requestId: nextId('audio-start'), sessionId: this.sessionId, utteranceId, revision,
        codec: config.codec, sampleRate: config.sampleRate, channels: config.channels, frameMs: config.frameMs,
      }))
      if (!audioStartSent) throw new Error('实时通道尚未就绪')
      this.audioStarted = true
      this.utteranceOpen = true
      await recorder.start()
      if (this.disposed || this.operation !== operation) {
        await this.discardRecorder(recorder)
        this.sendAudioEnd(utteranceId, revision)
        return false
      }
      this.dispatch({ type: 'recording', state: 'recording' })
      this.report('capture.recorder_started', {
        utteranceId,
        revision,
        attributes: { sampleRate: config.sampleRate, channels: config.channels, frameMs: config.frameMs },
      })
      this.maxRecordingTimer = setTimeout(() => { void this.stopRecording() }, 15_000)
      return true
    } catch (cause) {
      if (recorder) await this.discardRecorder(recorder)
      else this.pauseRecorder()
      if (audioStartSent) this.sendAudioEnd(utteranceId, revision)
      if (this.disposed || this.operation !== operation) return false
      const reason = cause instanceof Error ? cause.message : '麦克风暂不可用'
      const denied = /权限|Permission|NotAllowed/i.test(reason)
      this.report(denied ? 'capture.permission_denied' : 'capture.recorder_failed', {
        utteranceId,
        revision,
        status: 'error',
        attributes: { reason },
      })
      this.dispatch({ type: 'recording', state: Pcm16Recorder.supported ? 'error' : 'unsupported', message: reason })
      return false
    }
  }

  async stopRecording(): Promise<void> {
    ++this.operation
    const recorder = this.recorder
    if (!recorder && !this.audioStarted) return
    this.dispatch({ type: 'recording', state: 'stopping' })
    this.pauseRecorder()
    this.clearRecordingTimers()
    this.dispatch({ type: 'audio_level', level: 0 })
    this.sendAudioEnd()
    this.utteranceOpen = false
    this.report('capture.recorder_stopped')
    this.dispatch({ type: 'recording', state: 'idle' })
    this.dispatch({ type: 'phase', phase: 'thinking', message: '正在理解' })
  }

  async cancelRecording(): Promise<void> {
    ++this.operation
    const utteranceId = this.utteranceId
    const revision = this.revision
    await this.releaseRecorder()
    this.clearRecordingTimers()
    this.dispatch({ type: 'audio_level', level: 0 })
    if (this.audioStarted && this.transport?.isReady && this.sessionId) {
      this.transport.send(controlFrame('speech_end', {
        requestId: nextId('speech-end'), sessionId: this.sessionId,
        utteranceId, revision: revision || undefined, reason: 'voice_mode_stopped',
      }))
    }
    this.audioStarted = false
    this.utteranceOpen = false
    this.dispatch({ type: 'recording', state: 'idle', message: '实时对话已结束' })
    this.dispatch({ type: 'phase', phase: 'idle', message: '实时对话已结束' })
  }

  sendText(text: string, isFinal = true): boolean {
    const clean = text.trim()
    const transport = this.transport
    if (!clean || this.disposed || !transport?.isReady || !this.sessionId) return false
    if (!this.utteranceId || !this.utteranceOpen) {
      this.utteranceId = nextId('utt')
      this.revision += 1
      this.gate.reset(this.utteranceId, this.revision)
      this.dispatch({ type: 'revision', utteranceId: this.utteranceId, revision: this.revision })
    }
    const sent = transport.send(controlFrame('text', {
      requestId: nextId('text'), sessionId: this.sessionId, utteranceId: this.utteranceId,
      revision: this.revision, text: clean, isFinal,
    }))
    if (sent) this.utteranceOpen = !isFinal
    return sent
  }

  private async cancelCurrent(reason: string, notify: boolean): Promise<void> {
    ++this.operation
    const previousUtterance = this.utteranceId
    const previousRevision = this.revision
    this.pauseRecorder()
    this.clearRecordingTimers()
    this.dispatch({ type: 'audio_level', level: 0 })
    if (this.audioStarted) this.sendAudioEnd(previousUtterance, previousRevision)
    this.utteranceOpen = false
    this.playback?.interrupt()
    if (this.transport?.isReady && this.sessionId) {
      this.transport.send(controlFrame('interrupt', {
        requestId: nextId('interrupt'), sessionId: this.sessionId, runId: this.runId,
        utteranceId: this.utteranceId, revision: this.revision || undefined, reason,
      }))
    }
    this.dispatch({ type: 'recording', state: 'idle' })
    this.dispatch({ type: 'phase', phase: 'interrupting', message: '正在停止上一轮' })
    if (notify) this.readOptions().onInterrupt?.()
  }

  private async getRecorder(config: RealtimeClientConfig): Promise<Pcm16Recorder> {
    if (this.recorder && this.recorderConfig
      && this.recorderConfig.sampleRate === config.sampleRate
      && this.recorderConfig.channels === config.channels
      && this.recorderConfig.frameMs === config.frameMs) {
      return this.recorder
    }
    await this.releaseRecorder()
    this.recorderConfig = {
      sampleRate: config.sampleRate,
      channels: config.channels,
      frameMs: config.frameMs,
    }
    this.recorder = new Pcm16Recorder({
      sampleRate: config.sampleRate,
      channels: config.channels,
      frameMs: config.frameMs,
      // Deliberately absent: `config.maxAudioBufferBytes` is the server's
      // whole-utterance budget, not a transport budget. Feeding it in made the
      // recorder's backlog of *unsent* audio scale with the server, so a stalled
      // socket could hold a minute of already-spoken audio and deliver it far
      // too late. The recorder keeps its own bounded default instead.
      onChunk: (frame) => {
        const capture = this.activeCapture
        return capture ? this.sendAudioFrame(capture.transport, capture.config, capture.operation, frame) : false
      },
      onDrop: (count) => this.dispatch({ type: 'buffer', bytes: this.activeCapture?.transport.bufferedAmount ?? 0, dropped: count }),
      onLevel: (level) => this.handleAudioLevel(level),
    })
    return this.recorder
  }

  private pauseRecorder(): void {
    this.activeCapture = undefined
    this.recorder?.pause()
  }

  private async releaseRecorder(): Promise<void> {
    const recorder = this.recorder
    this.recorder = undefined
    this.recorderConfig = undefined
    this.activeCapture = undefined
    if (recorder) await recorder.stop()
  }

  private async discardRecorder(recorder: Pcm16Recorder): Promise<void> {
    if (this.recorder === recorder) {
      this.recorder = undefined
      this.recorderConfig = undefined
      this.activeCapture = undefined
    }
    await recorder.stop()
  }

  private sendAudioFrame(transport: RealtimeTransport, config: RealtimeClientConfig, operation: number, frame: ArrayBuffer): boolean {
    if (this.disposed || this.operation !== operation || this.transport !== transport || !transport.isReady) return false
    const maxFrameBytes = config.maxAudioFrameBytes ?? config.maxFrameBytes
    if (frame.byteLength !== (config.audioFrameBytes ?? pcmFrameBytes(config.sampleRate, config.frameMs, config.channels))) {
      this.dispatch({ type: 'buffer', bytes: transport.bufferedAmount, dropped: 1 })
      return false
    }
    if (transport.bufferedAmount > maxFrameBytes * 4) {
      this.dispatch({ type: 'buffer', bytes: transport.bufferedAmount, dropped: 1 })
      return false
    }
    const sent = transport.send(frame)
    this.dispatch({ type: 'buffer', bytes: transport.bufferedAmount, dropped: sent ? 0 : 1 })
    return sent
  }

  private handleAudioLevel(level: number): void {
    const normalized = Math.max(0, Math.min(1, level))
    this.dispatch({ type: 'audio_level', level: normalized })
    if (normalized >= SPEECH_LEVEL_THRESHOLD) {
      this.speechDetected = true
      // Track how loud the turn was: a decisive, loud finish lets the server
      // stop listening much sooner without cutting off a quiet trailing word.
      this.peakSpeechLevel = Math.max(this.peakSpeechLevel, normalized)
      this.trailingSpeechLevel = normalized
      if (this.silenceTimer) clearTimeout(this.silenceTimer)
      this.silenceTimer = undefined
      return
    }
    if (!this.speechDetected || this.silenceTimer) return
    const wait = endOfTurnSilenceMs(this.peakSpeechLevel, this.trailingSpeechLevel)
    this.silenceTimer = setTimeout(() => {
      this.silenceTimer = undefined
      if (this.recorder?.isRecording) void this.stopRecording()
    }, wait)
  }

  private clearRecordingTimers(): void {
    if (this.silenceTimer) clearTimeout(this.silenceTimer)
    if (this.maxRecordingTimer) clearTimeout(this.maxRecordingTimer)
    this.silenceTimer = undefined
    this.maxRecordingTimer = undefined
  }
  private sendAudioEnd(utteranceId = this.utteranceId, revision = this.revision): void {
    const decision = decideAudioEnd(
      this.audioStarted && this.utteranceId ? { utteranceId: this.utteranceId, revision: this.revision } : undefined,
      utteranceId && Number.isInteger(revision) ? { utteranceId, revision } : undefined,
      Boolean(this.transport?.isReady && this.sessionId),
    )
    if (!decision.accepted) return
    this.audioStarted = false
    if (!decision.shouldSend || !this.transport?.isReady || !this.sessionId || !utteranceId) return
    this.transport.send(controlFrame('audio_end', {
      requestId: nextId('audio-end'), sessionId: this.sessionId, utteranceId, revision: revision || undefined,
    }))
  }

  /**
   * Emit a browser-side marker onto the current run trace.
   *
   * The run trace is preferred, but capture happens before a run exists, so
   * connection-level markers fall back to the connection id. This keeps one
   * trace spanning "microphone opened" through "avatar finished speaking".
   */
  private report(
    name: string,
    options: {
      utteranceId?: string
      revision?: number
      runId?: string
      status?: 'ok' | 'error' | 'unset'
      durationMs?: number
      attributes?: Record<string, unknown>
    } = {},
  ): void {
    const traceId = this.traceId || this.connectionId
    if (!traceId) return
    reportClientEvent({
      name,
      traceId,
      runId: options.runId ?? this.runId,
      utteranceId: options.utteranceId ?? this.utteranceId,
      revision: options.revision ?? this.revision,
      durationMs: options.durationMs,
      status: options.status,
      attributes: options.attributes,
    })
  }

  private handleTransportState(state: RealtimeState['connection']): void {
    if (this.disposed) return
    this.dispatch({ type: 'connection', state })
    if (state === 'reconnecting' || state === 'closed' || state === 'error') {
      this.runId = undefined
      this.audioStarted = false
      this.playback?.interrupt()
      this.dispatch({ type: 'run', runId: undefined })
      if (this.recorder) {
        void this.releaseRecorder()
        this.dispatch({ type: 'recording', state: 'idle', message: '实时通道已断开，录音已停止' })
      }
    }
  }

  private handleReady(event: RealtimeInboundEvent): void {
    if (this.disposed) return
    if (event.connectionId) {
      this.connectionId = event.connectionId
      setTelemetryContext({ connectionId: event.connectionId })
    }
    const negotiated = this.transport?.negotiatedConfig
    if (negotiated) {
      this.config = negotiated
      this.playback?.interrupt()
      void this.playback?.close()
      this.playback = this.createPlayback(negotiated)
    }
    this.gate = new RealtimeEventGate()
    if (this.utteranceId) this.gate.reset(this.utteranceId, this.revision)
    const capabilities = event.capabilities
    this.dispatch({ type: 'connection', state: 'connected', connectionId: event.connectionId, traceId: this.traceId, message: '实时通道已连接' })
    this.report('realtime.client_connected', {
      attributes: { capabilities: Boolean(capabilities) },
    })
    if (capabilities) {
      const asr = capabilities.asr
      this.dispatch({
        type: 'capabilities',
        audioInput: this.supported && booleanCapability(capabilities.audioInput ?? capabilities.audio_input) !== false && !isUnsupportedCapability(asr),
        audioOutput: booleanCapability(capabilities.audioOutput ?? capabilities.audio_output),
        asr,
        tts: capabilities.tts,
      })
    }
  }

  private createPlayback(config: RealtimeClientConfig): Pcm16PlaybackQueue {
    return new Pcm16PlaybackQueue({
      sampleRate: config.sampleRate,
      channels: config.channels,
      onState: (state) => this.dispatch({ type: 'playback', state }),
      onDrop: (count) => this.dispatch({ type: 'buffer', bytes: 0, dropped: count }),
    })
  }

  private handleInbound(event: RealtimeInboundEvent): void {
    if (event.traceId) this.traceId = event.traceId
    if (event.connectionId) this.connectionId = event.connectionId
    handleRealtimeEvent(event, {
      gate: this.gate,
      playback: this.playback,
      dispatch: this.dispatch,
      stopRecording: () => this.stopRecording(),
      readTranscript: (text) => this.readOptions().onTranscript?.(text),
      readAssistant: (text, append) => this.readOptions().onAssistantText?.(text, append),
      revision: this.revision,
      utteranceId: this.utteranceId,
      setRevision: (revision) => { this.revision = revision },
      setUtteranceId: (utteranceId) => { this.utteranceId = utteranceId },
      setUtteranceOpen: (open) => { this.utteranceOpen = open },
      setRunId: (runId) => { this.runId = runId },
      disposed: this.disposed,
    })
    const kind = String(event.type ?? '').toLowerCase()
    if (kind === 'run_started' && event.runId) {
      this.dispatch({ type: 'run', runId: event.runId, traceId: this.traceId })
      this.report('realtime.phase', { runId: event.runId, attributes: { phase: 'running' } })
      return
    }
    if (kind === 'interrupted' || kind === 'run_done' || kind === 'done') {
      // The run is finished, so the browser's view of this trace is complete.
      // Flushing now keeps the report aligned with the server-side terminal
      // marker instead of leaving it queued behind a later run.
      flushClientEvents()
    }
  }
}
