import type { AvatarSession } from '../../shared/api/types'
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
  private playback?: Pcm16PlaybackQueue
  private revision = 0
  private utteranceId?: string
  private runId?: string
  private utteranceOpen = false
  private audioStarted = false
  private operation = 0
  private disposed = false

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
    const recorder = this.recorder
    this.recorder = undefined
    if (recorder) await recorder.stop()
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
    const recorder = this.recorder
    const previousUtterance = this.utteranceId
    const previousRevision = this.revision
    this.recorder = undefined
    if (recorder) await recorder.stop()
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
    const recorder = new Pcm16Recorder({
      sampleRate: config.sampleRate,
      channels: config.channels,
      frameMs: config.frameMs,
      maxPendingBytes: config.maxAudioBufferBytes,
      onChunk: (frame) => this.sendAudioFrame(transport, config, operation, frame),
      onDrop: (count) => this.dispatch({ type: 'buffer', bytes: transport.bufferedAmount, dropped: count }),
    })
    let audioStartSent = false
    try {
      audioStartSent = transport.send(controlFrame('audio_start', {
        requestId: nextId('audio-start'), sessionId: this.sessionId, utteranceId, revision,
        codec: config.codec, sampleRate: config.sampleRate, channels: config.channels, frameMs: config.frameMs,
      }))
      if (!audioStartSent) throw new Error('实时通道尚未就绪')
      this.audioStarted = true
      this.utteranceOpen = true
      await recorder.start()
      if (this.disposed || this.operation !== operation) {
        await recorder.stop()
        this.sendAudioEnd(utteranceId, revision)
        return false
      }
      this.recorder = recorder
      this.dispatch({ type: 'recording', state: 'recording' })
      return true
    } catch (cause) {
      await recorder.stop()
      if (audioStartSent) this.sendAudioEnd(utteranceId, revision)
      this.dispatch({ type: 'recording', state: Pcm16Recorder.supported ? 'error' : 'unsupported', message: cause instanceof Error ? cause.message : '麦克风暂不可用' })
      return false
    }
  }

  async stopRecording(): Promise<void> {
    ++this.operation
    const recorder = this.recorder
    this.recorder = undefined
    if (!recorder && !this.audioStarted) return
    this.dispatch({ type: 'recording', state: 'stopping' })
    if (recorder) await recorder.stop()
    this.sendAudioEnd()
    this.utteranceOpen = false
    this.dispatch({ type: 'recording', state: 'idle' })
    this.dispatch({ type: 'phase', phase: 'thinking', message: '正在理解' })
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
    const recorder = this.recorder
    const previousUtterance = this.utteranceId
    const previousRevision = this.revision
    this.recorder = undefined
    if (recorder) await recorder.stop()
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

  private handleTransportState(state: RealtimeState['connection']): void {
    if (this.disposed) return
    this.dispatch({ type: 'connection', state })
    if (state === 'reconnecting' || state === 'closed' || state === 'error') {
      this.runId = undefined
      this.audioStarted = false
      this.playback?.interrupt()
      this.dispatch({ type: 'run', runId: undefined })
      if (this.recorder) {
        void this.recorder.stop()
        this.recorder = undefined
        this.dispatch({ type: 'recording', state: 'idle', message: '实时通道已断开，录音已停止' })
      }
    }
  }

  private handleReady(event: RealtimeInboundEvent): void {
    if (this.disposed) return
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
    this.dispatch({ type: 'connection', state: 'connected', connectionId: event.connectionId, message: '实时通道已连接' })
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
  }
}
