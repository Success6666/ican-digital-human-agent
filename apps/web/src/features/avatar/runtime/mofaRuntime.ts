import type { AvatarClientParams } from '../../../shared/api/types'
import type { AvatarPerformanceCue } from '../../../shared/api/types'
import { reportClientEvent } from '../../observability/clientReporter'
import type { AvatarRuntimeStatus, AvatarTraceContext, BrowserAvatarRuntime } from './browserRuntime'
import { avatarAudioState, installAudioContextTracker, resumeTrackedAudio } from './audioUnlock'
import { buildMofaSpeechRequest } from './mofaSpeech'
import { createRuntimeId } from './runtimeId'
import { loadExternalScript } from './scriptLoader'

/** Vendor SDK speak calls are silent-failure prone; bound them explicitly. */
const SPEAK_COMPLETION_TIMEOUT_MS = 15_000

/**
 * How long a non-final segment waits for the SDK to acknowledge `speak_start`.
 *
 * The vendor SDK answers a segment submitted while the previous one is still
 * starting with a "speak_start 未结束" warning and silently drops the earlier
 * text. Waiting for the acknowledgement keeps the stream ordered, and this
 * bound guarantees a silent SDK can never stall the reply.
 */
const SPEAK_ACK_TIMEOUT_MS = 1_200

/**
 * Monotonic clock for speak latency.
 *
 * `performance` is not guaranteed in every evaluation sandbox, so fall back to
 * `Date.now` rather than letting instrumentation break the speech pipeline.
 */
function nowMilliseconds(): number {
  return typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? performance.now()
    : Date.now()
}

interface XmovAvatarInstance {
  init(options?: Record<string, unknown>): Promise<void>
  speak(text: string, isStart?: boolean, isEnd?: boolean, extra?: Record<string, unknown>): void
  interrupt(type: string): number
  interactiveidle(): void
  stop(): Promise<void> | void
  destroy(reason?: string): Promise<void> | void
  switchInvisibleMode(): number | void
  changeAvatarVisible(visible: boolean): void
  changeLayout(layout: Record<string, unknown>): void
}

interface XmovAvatarConstructor {
  new (options: Record<string, unknown>): XmovAvatarInstance
}

declare global {
  interface Window {
    XmovAvatar?: XmovAvatarConstructor
    CryptoJS?: unknown
    CryptoJSTest?: unknown
  }
}

interface MofaRuntimeConfig {
  sdkUrl: string
  cryptoUrl: string
  gatewayServer: string
  appId: string
  appSecret: string
  authorization?: string
  emotionEnabled: boolean
}

export class MofaBrowserRuntime implements BrowserAvatarRuntime {
  private avatar?: XmovAvatarInstance
  private status?: (status: AvatarRuntimeStatus) => void
  private speechBuffer = ''
  private pendingSpeech?: { text: string; presentation?: AvatarPerformanceCue }
  private speechGeneration = 0
  private activeSpeechId?: string
  private speechCompletion?: {
    generation: number
    clientSpeakId?: string
    promise: Promise<void>
    resolve: () => void
    reject: (error: Error) => void
    timer: number
  }
  private streamStarted = false
  private invisible = false
  private emotionEnabled = false
  /**
   * Serializes every `speak` call.
   *
   * The vendor SDK keeps one streaming utterance at a time. React re-runs the
   * speech effect on every delta, and a single call can also release several
   * clauses at once, so without this chain two `speak` calls overlap and the
   * SDK drops the earlier text — the avatar starts mid-sentence and its
   * opening words are never heard.
   */
  private speechChain: Promise<void> = Promise.resolve()
  private segmentAck?: { promise: Promise<void>; settle: () => void; timer: number }
  private releaseConsoleGuard?: () => void
  private connectionGeneration = 0
  private disposed = false
  private trace?: AvatarTraceContext
  private speakStartedAt?: number
  private speechTimedOut = false
  private ttsaWarningActive = false
  private lastAudioState?: string

  setTraceContext(context: AvatarTraceContext): void {
    this.trace = context
  }

  /**
   * Report a vendor-SDK speak lifecycle marker.
   *
   * These events never carry audio or SSML: only counts, timing and the SDK's
   * own state names, so a trace can show *that* the avatar was asked to speak
   * without leaking the content of the conversation into telemetry.
   */
  private report(
    name: string,
    options: {
      status?: 'ok' | 'error' | 'unset'
      durationMs?: number
      attributes?: Record<string, unknown>
    } = {},
  ): void {
    const traceId = this.trace?.traceId()
    if (!traceId) return
    reportClientEvent({
      name,
      traceId,
      runId: this.trace?.runId(),
      utteranceId: this.trace?.utteranceId(),
      revision: this.trace?.revision(),
      durationMs: options.durationMs,
      status: options.status,
      attributes: options.attributes,
    })
  }

  async connect(host: HTMLElement, params: AvatarClientParams, onStatus: (status: AvatarRuntimeStatus) => void): Promise<void> {
    const connectionGeneration = ++this.connectionGeneration
    this.disposed = false
    this.status = onStatus
    try {
      const config = requiredConfig(params)
      // Must run before the SDK is constructed: it makes its own AudioContext,
      // and a later gesture can only resume it if we are already watching for it.
      installAudioContextTracker()
      this.emotionEnabled = config.emotionEnabled
      onStatus({ phase: 'loading', progress: 0, message: '正在加载数字人运行时' })
      this.report('avatar.connect_started', {
        attributes: { sdkUrl: config.sdkUrl, gatewayOrigin: new URL(config.gatewayServer).origin },
      })
      await loadExternalScript(config.cryptoUrl, () => Boolean(window.CryptoJS))
      this.assertConnectionActive(connectionGeneration)
      window.CryptoJSTest = window.CryptoJS
      await loadExternalScript(config.sdkUrl, () => Boolean(window.XmovAvatar))
      this.assertConnectionActive(connectionGeneration)
      if (!window.XmovAvatar) throw new Error('魔珐数字人 SDK 不可用')

      const containerId = ensureContainerId(host)
      const gateway = normalizeGatewayUrl(config.gatewayServer)
      let signalFirstFrame!: () => void
      const firstFrame = new Promise<void>((resolve) => { signalFirstFrame = resolve })
      let initialized = false
      let rendered = false
      let ttsaWarning = false
      let readinessReported = false
      const currentConnection = () => this.isConnectionActive(connectionGeneration)
      const report = (status: AvatarRuntimeStatus) => {
        if (currentConnection()) onStatus(status)
      }
      const markReady = (caller: string) => {
        signalFirstFrame()
        if (!currentConnection()) {
          this.report('avatar.ready_blocked', { attributes: { reason: 'connection_dropped', caller } })
          return
        }
        if (!initialized) {
          this.report('avatar.ready_blocked', { attributes: { reason: 'not_initialized', caller } })
          return
        }
        if (ttsaWarning) {
          this.report('avatar.ready_blocked', { attributes: { reason: 'ttsa_warning', caller } })
          return
        }
        if (rendered) return
        rendered = true
        if (!readinessReported) {
          readinessReported = true
          this.report('avatar.ready_achieved', { attributes: { caller } })
        }
        report({ phase: 'ready', progress: 100, message: '数字人已连接' })
      }

      const headers = config.authorization ? { Authorization: config.authorization } : undefined
      this.releaseConsoleGuard?.()
      this.releaseConsoleGuard = acquireMofaConsoleGuard()
      debugMofa('SDK init', {
        sdkUrl: config.sdkUrl,
        gatewayOrigin: gateway.origin,
        gatewayPath: gateway.pathname,
        gatewayQueryKeys: [...gateway.searchParams.keys()],
        hasAppId: Boolean(config.appId),
        hasAppSecret: Boolean(config.appSecret),
        hasAuthorization: Boolean(config.authorization),
      })
      const avatar = new window.XmovAvatar({
        containerId: `#${containerId}`,
        appId: config.appId,
        appSecret: config.appSecret,
        ...(headers ? { headers } : {}),
        enableDebugger: false,
        enableLogger: true,
        enableClientInterrupt: true,
        gatewayServer: gateway.toString(),
        onMessage: (message: { code?: string | number; message?: string }) => {
          if (!currentConnection()) return
          debugMofa('SDK message', message)
          const detail = sdkMessage(message)
          const networkState = sdkNetworkState(message)
          if (networkState === 'reconnecting') {
            report({ phase: 'loading', progress: 90, message: '网络波动，正在自动重连' })
            return
          }
          if (networkState === 'online') {
            ttsaWarning = false
            this.markTtsaRecovered()
            markReady('onMessage:online')
            return
          }
          if (isSpeechOverlapWarning(detail)) {
            console.warn('[Mofa Runtime] recovered overlapping speech boundary', sanitizeMofaDiagnostic(message))
            report({ phase: 'speaking', progress: 100, message: '数字人正在表达' })
            return
          }
          if (isRecoverableTtsaError(message, detail)) {
            ttsaWarning = true
            this.markTtsaWarning(message, detail)
            report({ phase: 'warning', progress: 100, message: formatTtsaError(message, detail) })
            return
          }
          if (detail) report({ phase: 'error', message: `星云运行时：${sanitizeMofaString(detail)}` })
        },
        onStartSessionWarning: (message: unknown) => {
          if (!currentConnection()) return
          debugMofa('SDK session warning', message)
          const detail = sdkMessage(message)
          if (detail) {
            console.warn('[Mofa Runtime] session warning', sanitizeMofaDiagnostic(message))
            if (isSpeechOverlapWarning(detail)) {
              report({ phase: 'ready', progress: 100, message: '数字人已连接，正在恢复表达' })
              return
            }
            if (isRecoverableTtsaError(message, detail)) {
              ttsaWarning = true
              this.markTtsaWarning(message, detail)
              report({ phase: 'warning', progress: 100, message: formatTtsaError(message, detail) })
              return
            }
            report({ phase: 'loading', progress: 85, message: sanitizeMofaString(detail) })
          }
        },
        onSpeakStateChange: (state: string, clientSpeakId?: string | number) => {
          if (!currentConnection()) return
          debugMofa('SDK speak state', { state, clientSpeakId })
          this.handleSpeakStateChange(state, clientSpeakId)
        },
        onVoiceStateChange: (state: string, duration?: number) => {
          if (currentConnection()) debugMofa('SDK voice state', { state, duration })
        },
        onNetworkInfo: (info: unknown) => {
          if (currentConnection()) debugMofa('SDK network info', info)
        },
        onStateChange: (state: unknown) => {
          if (currentConnection()) debugMofa('SDK state', state)
        },
        onStateRenderChange: (state: unknown) => {
          if (!currentConnection()) return
          debugMofa('SDK render state', state)
          if (String(state).toLowerCase().includes('render')) markReady('onStateRenderChange')
        },
        onStatusChange: (state: unknown) => {
          if (!currentConnection()) return
          debugMofa('SDK status state', state)
          const normalized = normalizeSdkStatus(state)
          if (normalized === 'ready') markReady('onStatusChange:ready')
          if (normalized === 'reconnecting') report({ phase: 'loading', progress: 90, message: '数字人连接恢复中' })
          if (normalized === 'closed') report({ phase: 'error', message: '数字人连接已断开，请重新连接' })
        },
      })
      this.assertConnectionActive(connectionGeneration)
      this.avatar = avatar

      const initPromise = Promise.resolve(avatar.init({
        onDownloadProgress: (progress: number) => {
          if (!currentConnection() || rendered) return
          const normalized = progress <= 1 ? progress * 100 : progress
          const value = Math.max(0, Math.min(100, Math.round(normalized)))
          report({ phase: 'loading', progress: value, message: '正在加载数字人资源' })
        },
      }))
      await withTimeout(initPromise, 60_000)
      this.assertConnectionActive(connectionGeneration)
      initialized = true
      await Promise.race([firstFrame, delay(2_000)])
      this.assertConnectionActive(connectionGeneration)
      await waitForStablePaint()
      this.assertConnectionActive(connectionGeneration)
      const width = Math.max(320, Math.round(host.clientWidth || 960))
      const height = Math.max(320, Math.round(host.clientHeight || 720))
      avatar.changeLayout({
        container: { size: [width, height] },
        avatar: { h_align: 'center', v_align: 'bottom', scale: Math.min(0.36, Math.max(0.28, (height / 1920) * 0.98)) },
      })
      markReady('connect:final')
      if (this.invisible) this.applyVisibility()
    } catch (cause) {
      const detail = cause instanceof Error ? cause.message : String(cause)
      this.report('avatar.connect_failed', {
        status: 'error',
        attributes: {
          reason: sanitizeMofaString(detail),
          phase: this.isConnectionActive(connectionGeneration) ? 'connect_in_progress' : 'connect_dropped',
        },
      })
      if (this.isConnectionActive(connectionGeneration)) await this.dispose()
      throw new Error(sanitizeMofaString(detail))
    }
  }

  private isConnectionActive(generation: number): boolean {
    return !this.disposed && this.connectionGeneration === generation
  }

  private assertConnectionActive(generation: number): void {
    if (!this.isConnectionActive(generation)) throw new Error('数字人连接已取消')
  }

  /**
   * Record whether the page can actually make sound at the moment of speaking.
   *
   * Only reported when the state changes: a suspended context is a permanent
   * condition on a phone that was never unlocked, so repeating it per segment
   * would bury the rest of the trace.
   */
  private reportAudioState(): void {
    const audio = avatarAudioState()
    const key = `${audio.state}:${audio.trackedCount}`
    if (this.lastAudioState === key) return
    this.lastAudioState = key
    if (audio.state === 'running') {
      this.report('avatar.audio_unlocked', {
        attributes: { state: audio.state, trackedCount: audio.trackedCount },
      })
      return
    }
    this.report('avatar.audio_blocked', {
      status: 'error',
      attributes: { state: audio.state, trackedCount: audio.trackedCount },
    })
  }

  private markTtsaWarning(message: unknown, detail: string): void {
    if (this.ttsaWarningActive) return
    this.ttsaWarningActive = true
    const code = typeof message === 'object' && message !== null ? Number((message as { code?: unknown }).code) : Number.NaN
    // A TTSA warning blocks `markReady`, which is exactly the branch that makes
    // the avatar go silent. Record it so silence is never an unexplained gap.
    this.report('ttsa.warning', {
      status: 'error',
      attributes: {
        reason: sanitizeMofaString(detail),
        ...(Number.isFinite(code) ? { code } : {}),
      },
    })
  }

  private markTtsaRecovered(): void {
    if (!this.ttsaWarningActive) return
    this.ttsaWarningActive = false
    this.report('ttsa.recovered')
  }

  private handleSpeakStateChange(state: string, clientSpeakId?: string | number): void {
    const key = clientSpeakId === undefined || clientSpeakId === null ? undefined : String(clientSpeakId)
    if (state === 'speak_start') {
      if (key) this.activeSpeechId = key
      if (this.speechCompletion && !this.speechCompletion.clientSpeakId && key) this.speechCompletion.clientSpeakId = key
      const durationMs = this.speakStartedAt === undefined ? undefined : Math.max(0, nowMilliseconds() - this.speakStartedAt)
      this.speakStartedAt = undefined
      // The SDK owns this segment now; the stream may hand over the next one.
      this.finishSegmentAck()
      this.report('speak.started', { durationMs, attributes: key ? { clientSpeakId: key } : undefined })
      return
    }

    // A terminal state is always reported, even when no completion promise is
    // waiting: the avatar going quiet after a failed segment is exactly the
    // failure this trace exists to explain, and it must not be dropped just
    // because the segment was a non-final one.
    if (state === 'speak_end' || state === 'end') {
      this.report('speak.ended', { attributes: key ? { clientSpeakId: key } : undefined })
      if (this.matchesCompletion(key)) {
        this.finishSpeechCompletion()
        this.activeSpeechId = undefined
      }
      return
    }
    if (state === 'speak_error' || state === 'error') {
      this.report('speak.failed', { status: 'error', attributes: { reason: 'speak_error', ...(key ? { clientSpeakId: key } : {}) } })
      if (this.matchesCompletion(key)) this.failSpeechCompletion(new Error('星云播报失败'))
    }
  }

  /** True when a terminal SDK state belongs to the completion we are waiting on. */
  private matchesCompletion(key?: string): boolean {
    const completion = this.speechCompletion
    if (!completion || completion.generation !== this.speechGeneration) return false
    if (completion.clientSpeakId && key && completion.clientSpeakId !== key) return false
    return true
  }

  setVisibility(visible: boolean): void {
    const nextInvisible = !visible
    if (this.invisible === nextInvisible) return
    this.invisible = nextInvisible
    this.applyVisibility()
  }

  async speak(text: string, presentation?: AvatarPerformanceCue, options?: { flush?: boolean }): Promise<void> {
    // Every call joins one chain so segments reach the SDK in order. Without
    // this, concurrent calls make the SDK discard the segment that had not
    // finished starting, which is heard as the avatar skipping to the end of
    // its answer.
    const run = this.speechChain.then(
      () => this.speakOrdered(text, presentation, options),
      () => this.speakOrdered(text, presentation, options),
    )
    // One rejected segment must not poison every call that follows it.
    this.speechChain = run.then(() => undefined, () => undefined)
    return run
  }

  private async speakOrdered(text: string, presentation?: AvatarPerformanceCue, options?: { flush?: boolean }): Promise<void> {
    const clean = text.trim()
    const flush = Boolean(options?.flush)
    if (!this.avatar || (!clean && !flush)) return
    // Captured once so a later interrupt can be recognised: `speechGeneration`
    // moves on when the utterance is abandoned, and everything queued before
    // that belongs to an answer the user is no longer listening to.
    const generation = this.speechGeneration
    if (clean) this.speechBuffer += clean
    while (true) {
      if (!this.speechBuffer.trim()) break
      // The opening segment is what actually makes the avatar start talking, so
      // it is released on a much shorter buffer: waiting for a full clause here
      // is felt directly as "the avatar takes a moment to answer". Once speech
      // is flowing, a longer buffer keeps prosody and motion stable.
      const boundary = findSpeechBoundary(this.speechBuffer, flush, !this.streamStarted)
      if (boundary < 0) break
      const segment = this.speechBuffer.slice(0, boundary).trim()
      this.speechBuffer = this.speechBuffer.slice(boundary).trimStart()
      if (!segment) continue
      if (this.pendingSpeech) {
        // Awaited, not fire-and-forget: releasing several clauses in one pass
        // used to issue them all at once and lose every one but the last.
        await this.dispatchSpeechSegment(this.pendingSpeech, false, generation).catch((cause) => {
          debugMofa('SDK non-final speak failed', cause)
          this.status?.({ phase: 'error', message: cause instanceof Error ? cause.message : '数字人播报失败' })
        })
        // `await` above is exactly where an interrupt lands. The clause was cut
        // before the wait, so re-queueing it here would let text from the
        // abandoned answer open the next one.
        if (generation !== this.speechGeneration) {
          this.pendingSpeech = undefined
          return
        }
      }
      this.pendingSpeech = { text: segment, presentation }
    }
    if (!flush) return
    if (generation !== this.speechGeneration) {
      this.pendingSpeech = undefined
      return
    }

    // `findSpeechBoundary` only releases whole clauses, so whatever is still in
    // the buffer when the stream closes is real content. Merging it keeps the
    // tail of an answer from being silently dropped.
    const leftover = this.speechBuffer.trim()
    this.speechBuffer = ''
    const queued = this.pendingSpeech
    this.pendingSpeech = undefined
    let finalSegment: { text: string; presentation?: AvatarPerformanceCue } | undefined
    if (queued && leftover) finalSegment = { text: `${queued.text}${leftover}`, presentation: queued.presentation }
    else if (queued) finalSegment = queued
    else if (leftover) finalSegment = { text: leftover, presentation }

    if (!finalSegment) {
      if (!this.streamStarted) this.status?.({ phase: 'ready', message: '数字人已连接' })
      return
    }
    await this.dispatchSpeechSegment(finalSegment, true, generation)
  }

  async interrupt(): Promise<void> {
    if (!this.avatar) return
    // Anything not handed to the SDK yet is about to be lost. Recording the
    // volume makes "the avatar stopped early" visible instead of silent.
    const pendingLength = this.speechBuffer.trim().length + (this.pendingSpeech?.text.length ?? 0)
    this.speechBuffer = ''
    this.pendingSpeech = undefined
    this.streamStarted = false
    this.speechGeneration += 1
    this.activeSpeechId = undefined
    this.finishSegmentAck()
    this.finishSpeechCompletion()
    if (pendingLength > 0) {
      this.report('speech.interrupted', { attributes: { pendingLength } })
    }
    this.avatar.interrupt('user_speaking')
    this.status?.({ phase: 'ready', message: '已停止上一轮表达' })
  }

  async dispose(): Promise<void> {
    this.disposed = true
    this.connectionGeneration += 1
    this.speechBuffer = ''
    this.pendingSpeech = undefined
    this.streamStarted = false
    this.speechGeneration += 1
    this.activeSpeechId = undefined
    this.finishSegmentAck()
    this.finishSpeechCompletion()
    const current = this.avatar
    this.avatar = undefined
    this.status = undefined
    this.emotionEnabled = false
    this.releaseConsoleGuard?.()
    this.releaseConsoleGuard = undefined
    if (!current) return
    try { await current.stop() } catch { /* SDK teardown remains best effort. */ }
    try { await current.destroy('component_unmounted') } catch { /* Host removal is the final cleanup boundary. */ }
  }

  private applyVisibility(): void {
    if (!this.avatar) return
    if (this.invisible) {
      this.avatar.changeAvatarVisible(false)
      this.avatar.switchInvisibleMode()
      return
    }
    this.avatar.changeAvatarVisible(true)
    this.avatar.switchInvisibleMode()
  }

  private async dispatchSpeechSegment(
    segment: { text: string; presentation?: AvatarPerformanceCue },
    isEnd: boolean,
    generation: number,
  ): Promise<void> {
    if (!this.avatar) {
      // Dropping a segment here used to be completely silent, which is how the
      // start of an answer could vanish with the trace still looking clean.
      this.report('speech.dropped', {
        status: 'error',
        attributes: { reason: 'avatar_unavailable', textLength: segment.text.length, isEnd },
      })
      return
    }
    if (generation !== this.speechGeneration) {
      // The utterance was interrupted while this segment waited its turn.
      // Sending it would splice the abandoned answer into the current one.
      this.report('speech.dropped', {
        status: 'error',
        attributes: { reason: 'generation_changed', textLength: segment.text.length, isEnd },
      })
      return
    }
    const request = buildMofaSpeechRequest(segment.text, segment.presentation, { enableEmotion: this.emotionEnabled })
    const extra = Object.keys(request.extra).length ? request.extra : undefined
    const isStart = !this.streamStarted
    // A suspended AudioContext is why a phone plays nothing while a desktop is
    // fine. Try to recover one that lapsed, then record what we ended up with.
    resumeTrackedAudio()
    this.reportAudioState()
    debugMofa('SDK speak dispatched', {
      isStart,
      isEnd,
      textLength: segment.text.length,
      hasExtra: Boolean(extra),
    })
    if (!isEnd) {
      const ack = this.createSegmentAck(generation)
      this.speakStartedAt = nowMilliseconds()
      this.avatar.speak(request.ssml, isStart, false, extra)
      this.streamStarted = true
      this.report('speak.dispatched', {
        attributes: { isStart, isEnd, textLength: segment.text.length, hasEmotion: Boolean(extra) },
      })
      this.status?.({ phase: 'speaking', message: '数字人正在表达' })
      // Hold the next segment until the SDK owns this one. Submitting while
      // the previous `speak_start` is still pending is what made the SDK drop
      // the earlier clause and jump the avatar to the end of its answer.
      await ack.promise
      return
    }

    // The final clause gets its own `speak_start` from the SDK. Clearing the
    // previous id lets the completion bind to that one — otherwise it waits
    // for an end event carrying an earlier clause's id, and a perfectly good
    // utterance times out after being spoken in full.
    this.activeSpeechId = undefined
    const completion = this.createSpeechCompletion(generation)
    this.speechCompletion = completion
    this.speechTimedOut = false
    this.speakStartedAt = nowMilliseconds()
    this.avatar.speak(request.ssml, isStart, true, extra)
    this.streamStarted = true
    this.report('speak.dispatched', {
      attributes: { isStart, isEnd, textLength: segment.text.length, hasEmotion: Boolean(extra) },
    })
    this.status?.({ phase: 'speaking', message: '数字人正在表达' })
    try {
      await completion.promise
    } catch (cause) {
      if (generation === this.speechGeneration) {
        this.streamStarted = false
        this.activeSpeechId = undefined
      }
      debugMofa('SDK speak failed', { clientSpeakId: completion.clientSpeakId, cause })
      // A timeout already reported `speak.timeout`; only report the remaining
      // failure modes so one broken utterance does not produce two markers.
      if (!this.speechTimedOut) {
        this.report('speak.failed', {
          status: 'error',
          attributes: { reason: cause instanceof Error ? cause.message : 'speak_failed' },
        })
      }
      throw cause
    } finally {
      if (this.speechCompletion === completion) this.speechCompletion = undefined
      window.clearTimeout(completion.timer)
    }
    if (generation !== this.speechGeneration || !this.avatar) return
    this.avatar.interactiveidle()
    this.streamStarted = false
    this.activeSpeechId = undefined
    this.status?.({ phase: 'ready', progress: 100, message: '数字人已连接' })
  }

  private createSpeechCompletion(generation: number): {
    generation: number
    clientSpeakId?: string
    promise: Promise<void>
    resolve: () => void
    reject: (error: Error) => void
    timer: number
  } {
    let resolvePromise!: () => void
    let rejectPromise!: (error: Error) => void
    const promise = new Promise<void>((resolve, reject) => {
      resolvePromise = resolve
      rejectPromise = reject
    })
    const completion = {
      generation,
      clientSpeakId: this.activeSpeechId,
      promise,
      resolve: resolvePromise,
      reject: rejectPromise,
      timer: 0,
    }
    completion.timer = window.setTimeout(() => {
      if (this.speechCompletion !== completion || generation !== this.speechGeneration) return
      this.speechCompletion = undefined
      this.speechTimedOut = true
      this.avatar?.interrupt('speak_timeout')
      // Silence with no terminal marker is the hardest failure to diagnose,
      // so both the trace and the operator are told why the avatar stopped.
      this.report('speak.timeout', {
        status: 'error',
        durationMs: SPEAK_COMPLETION_TIMEOUT_MS,
        attributes: { reason: 'speak_timeout', clientSpeakId: completion.clientSpeakId },
      })
      completion.reject(new Error('星云播报超时'))
    }, SPEAK_COMPLETION_TIMEOUT_MS)
    return completion
  }

  /**
   * Gate the next segment on the SDK acknowledging this one.
   *
   * The acknowledgement is only a "the SDK took it" signal, never a wait for
   * playback to finish — speech still streams. It resolves on timeout as well,
   * so an SDK that never calls back slows the stream but cannot stall it.
   */
  private createSegmentAck(generation: number): { promise: Promise<void>; settle: () => void; timer: number } {
    let settle!: () => void
    const promise = new Promise<void>((resolve) => { settle = resolve })
    const ack = {
      promise,
      settle,
      timer: window.setTimeout(() => {
        if (this.segmentAck !== ack) return
        this.segmentAck = undefined
        // Continuing without the acknowledgement risks an overlap warning, so
        // the trace records the gap rather than letting the text just vanish.
        this.report('speech.ack_timeout', {
          status: 'error',
          durationMs: SPEAK_ACK_TIMEOUT_MS,
          attributes: { reason: 'speak_start_missing' },
        })
        settle()
      }, SPEAK_ACK_TIMEOUT_MS),
    }
    if (generation === this.speechGeneration) this.segmentAck = ack
    else settle()
    return ack
  }

  private finishSegmentAck(): void {
    const ack = this.segmentAck
    if (!ack) return
    this.segmentAck = undefined
    window.clearTimeout(ack.timer)
    ack.settle()
  }

  private finishSpeechCompletion(): void {
    const completion = this.speechCompletion
    if (!completion) return
    this.speechCompletion = undefined
    window.clearTimeout(completion.timer)
    completion.resolve()
  }

  private failSpeechCompletion(error: Error): void {
    const completion = this.speechCompletion
    if (!completion) return
    this.speechCompletion = undefined
    window.clearTimeout(completion.timer)
    completion.reject(error)
  }

}

function debugMofa(event: string, detail?: unknown): void {
  if (detail === undefined) {
    console.info(`[Mofa Runtime] ${event}`)
    return
  }
  console.info(`[Mofa Runtime] ${event}`, sanitizeMofaDiagnostic(detail))
}

type MofaConsoleMethod = 'debug' | 'info' | 'log' | 'warn' | 'error'
const MOFA_CONSOLE_METHODS: MofaConsoleMethod[] = ['debug', 'info', 'log', 'warn', 'error']
let mofaConsoleGuardUsers = 0
let mofaConsoleOriginals: Partial<Record<MofaConsoleMethod, (...args: unknown[]) => void>> | undefined

function acquireMofaConsoleGuard(): () => void {
  if (mofaConsoleGuardUsers === 0) {
    mofaConsoleOriginals = {}
    for (const method of MOFA_CONSOLE_METHODS) {
      const original = console[method].bind(console) as (...args: unknown[]) => void
      mofaConsoleOriginals[method] = original
      console[method] = (...args: unknown[]) => original(...args.map((value) => sanitizeMofaDiagnostic(value)))
    }
  }
  mofaConsoleGuardUsers += 1
  let released = false
  return () => {
    if (released) return
    released = true
    mofaConsoleGuardUsers -= 1
    if (mofaConsoleGuardUsers > 0 || !mofaConsoleOriginals) return
    for (const method of MOFA_CONSOLE_METHODS) {
      const original = mofaConsoleOriginals[method]
      if (original) console[method] = original
    }
    mofaConsoleOriginals = undefined
  }
}

function sanitizeMofaDiagnostic(value: unknown, seen = new WeakSet<object>()): unknown {
  if (value instanceof Error) return { name: value.name, message: sanitizeMofaString(value.message) }
  if (typeof value === 'string') return sanitizeMofaString(value)
  if (value === null || typeof value !== 'object') return value
  if (seen.has(value)) return '[circular]'
  seen.add(value)
  if (Array.isArray(value)) return value.slice(0, 32).map((item) => sanitizeMofaDiagnostic(item, seen))
  const output: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value as Record<string, unknown>).slice(0, 64)) {
    if (/authorization|secret|token|password|cookie|api[-_]?key|signature|session(?:[_-]?id)?/i.test(key)) {
      output[key] = '<redacted>'
    } else if (/(?:url|uri|gateway(?:[_-]?server)?)$/i.test(key) && typeof item === 'string') {
      output[key] = sanitizeMofaUrl(item)
    } else {
      output[key] = sanitizeMofaDiagnostic(item, seen)
    }
  }
  return output
}

function sanitizeMofaString(value: string): string {
  return value
    .replace(/(["']?(?:authorization|app[_-]?secret|token|password|api[-_]?key|signature|session(?:[_-]?id)?)["']?\s*[:=]\s*["']?)(?:Bearer\s+)?([^"'\s,}&]+)(["']?)/gi, '$1<redacted>$3')
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, 'Bearer <redacted>')
    .slice(0, 2000)
}

function sanitizeMofaUrl(value: string): string {
  try {
    const url = new URL(value)
    for (const key of [...url.searchParams.keys()]) {
      if (/authorization|secret|token|password|api[_-]?key|signature|session(?:[_-]?id)?/i.test(key)) url.searchParams.set(key, '<redacted>')
    }
    return url.toString()
  } catch {
    return sanitizeMofaString(value)
  }
}

/**
 * Length the buffer must reach before a segment is released.
 *
 * The opening segment uses a much smaller threshold so the avatar begins
 * speaking as soon as there is a phrase worth saying. Later segments favour a
 * larger buffer so the mouth and emotion stay in step with the text.
 */
const OPENING_SPEECH_MIN_CHARS = 6
const STEADY_SPEECH_MIN_CHARS = 16

function findSpeechBoundary(value: string, flush: boolean, opening = false): number {
  const punctuation = /[。！？!?；;，,\n]/g
  let match: RegExpExecArray | null
  while ((match = punctuation.exec(value))) return match.index + 1
  const threshold = opening ? OPENING_SPEECH_MIN_CHARS : STEADY_SPEECH_MIN_CHARS
  if (value.trim().length >= threshold || flush) return value.length
  return -1
}

function requiredConfig(params: AvatarClientParams): MofaRuntimeConfig {
  const values = {
    sdkUrl: params.sdkUrl, cryptoUrl: params.cryptoUrl, gatewayServer: params.gatewayServer,
    appId: params.appId, appSecret: params.appSecret, authorization: params.authorization,
    emotionEnabled: params.emotionEnabled === true,
  }
  for (const [name, value] of Object.entries(values)) {
    if (name === 'authorization' || name === 'emotionEnabled') continue
    if (!value) throw new Error(`魔珐数字人缺少 ${name} 配置`)
  }
  return values as MofaRuntimeConfig
}

function ensureContainerId(host: HTMLElement): string {
  if (!host.id) host.id = `mofa-avatar-${createRuntimeId()}`
  return host.id
}

function normalizeGatewayUrl(value: string): URL {
  const gateway = new URL(value)
  // The SDK starts the session with a signed HTTP POST/fetch. The
  // response contains the WebSocket URL used internally for TTSA streaming.
  if (gateway.protocol === 'wss:') gateway.protocol = 'https:'
  if (gateway.protocol === 'ws:') gateway.protocol = 'http:'
  if (gateway.protocol !== 'https:' && gateway.protocol !== 'http:') throw new Error('魔珐会话网关必须使用 http 或 https')
  return gateway
}

function sdkMessage(value: unknown): string {
  if (typeof value === 'string') return value
  if (!value || typeof value !== 'object') return value == null ? '' : String(value)
  const record = value as Record<string, unknown>
  for (const key of ['message', 'error_reason', 'reason', 'detail']) {
    if (typeof record[key] === 'string' && record[key]) return record[key] as string
  }
  const compact = Object.entries(record)
    .filter(([, item]) => ['string', 'number', 'boolean'].includes(typeof item))
    .map(([key, item]) => `${key}: ${String(item)}`)
    .join('；')
  return compact
}

function isRecoverableTtsaError(value: unknown, detail: string): boolean {
  const code = typeof value === 'object' && value !== null ? Number((value as { code?: unknown }).code) : Number.NaN
  const normalized = detail.toLowerCase()
  return [1, 40006].includes(code)
    || normalized.includes('ttsa 返回异常')
    || normalized.includes('暂无空闲房间')
    || normalized.includes('no idle room')
}

function formatTtsaError(value: unknown, detail: string): string {
  const code = typeof value === 'object' && value !== null ? Number((value as { code?: unknown }).code) : Number.NaN
  const safeDetail = sanitizeMofaString(detail)
  if (safeDetail && !['ttsa 返回异常', 'ttsa error'].includes(safeDetail.trim().toLowerCase())) {
    return `TTSA 暂不可用：${safeDetail}${Number.isFinite(code) ? `（错误码 ${code}）` : ''}`
  }
  return `TTSA 暂不可用${Number.isFinite(code) ? `（错误码 ${code}）` : ''}，请稍后重试`
}

function isSpeechOverlapWarning(value: string): boolean {
  const normalized = value.toLowerCase()
  return normalized.includes('speak_start') && (
    normalized.includes('未结束') || normalized.includes('not end') || normalized.includes('previous')
  )
}

function sdkNetworkState(value: { code?: string | number; message?: string }): 'online' | 'reconnecting' | undefined {
  const code = Number(value.code)
  const detail = `${value.code ?? ''} ${value.message ?? ''}`.toLowerCase()
  if ([50002, 3502].includes(code) || detail.includes('network_up')) return 'online'
  if ([50001, 50003, 3501, 3503].includes(code) || detail.includes('network_down') || detail.includes('network_retry')) return 'reconnecting'
  return undefined
}

function normalizeSdkStatus(value: unknown): 'ready' | 'reconnecting' | 'closed' | 'unknown' {
  const numeric = typeof value === 'number' ? value : Number.NaN
  if ([0, 2, 5].includes(numeric)) return 'ready'
  if ([1, 3].includes(numeric)) return 'reconnecting'
  if ([4, 7].includes(numeric)) return 'closed'
  const normalized = String(value).toLowerCase()
  if (normalized.includes('visible') || normalized.includes('online') || normalized.includes('network_on')) return 'ready'
  if (normalized.includes('offline') || normalized.includes('network_off')) return 'reconnecting'
  if (normalized.includes('close') || normalized.includes('stopped')) return 'closed'
  return 'unknown'
}

async function withTimeout<T>(operation: Promise<T>, timeoutMs: number): Promise<T> {
  let timer = 0
  const timeout = new Promise<never>((_, reject) => {
    timer = window.setTimeout(() => reject(new Error('数字人初始化超时')), timeoutMs)
  })
  try { return await Promise.race([operation, timeout]) } finally { window.clearTimeout(timer) }
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

async function waitForStablePaint(timeoutMs = 1_000): Promise<void> {
  // Bounded on purpose: a background tab or an occluded window can stop
  // delivering animation frames altogether. Waiting forever for a frame the
  // browser will never deliver left the runtime stuck on "正在加载数字人资源
  // 80%" — connected, downloading finished, but never ready, with no error.
  await Promise.race([
    new Promise<void>((resolve) => window.requestAnimationFrame(() => window.requestAnimationFrame(() => resolve()))),
    delay(timeoutMs),
  ])
}
