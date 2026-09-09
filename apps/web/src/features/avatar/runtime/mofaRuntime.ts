import type { AvatarClientParams } from '../../../shared/api/types'
import type { AvatarPerformanceCue } from '../../../shared/api/types'
import type { AvatarRuntimeStatus, BrowserAvatarRuntime } from './browserRuntime'
import { buildMofaSpeechRequest } from './mofaSpeech'
import { createRuntimeId } from './runtimeId'
import { loadExternalScript } from './scriptLoader'

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
  private releaseConsoleGuard?: () => void
  private connectionGeneration = 0
  private disposed = false

  async connect(host: HTMLElement, params: AvatarClientParams, onStatus: (status: AvatarRuntimeStatus) => void): Promise<void> {
    const connectionGeneration = ++this.connectionGeneration
    this.disposed = false
    this.status = onStatus
    try {
      const config = requiredConfig(params)
      this.emotionEnabled = config.emotionEnabled
      onStatus({ phase: 'loading', progress: 0, message: '正在加载数字人运行时' })
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
      const currentConnection = () => this.isConnectionActive(connectionGeneration)
      const report = (status: AvatarRuntimeStatus) => {
        if (currentConnection()) onStatus(status)
      }
      const markReady = () => {
        signalFirstFrame()
        if (!currentConnection() || !initialized || ttsaWarning || rendered) return
        rendered = true
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
            markReady()
            return
          }
          if (isSpeechOverlapWarning(detail)) {
            console.warn('[Mofa Runtime] recovered overlapping speech boundary', sanitizeMofaDiagnostic(message))
            report({ phase: 'speaking', progress: 100, message: '数字人正在表达' })
            return
          }
          if (isRecoverableTtsaError(message, detail)) {
            ttsaWarning = true
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
          if (String(state).toLowerCase().includes('render')) markReady()
        },
        onStatusChange: (state: unknown) => {
          if (!currentConnection()) return
          debugMofa('SDK status state', state)
          const normalized = normalizeSdkStatus(state)
          if (normalized === 'ready') markReady()
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
      markReady()
      if (this.invisible) this.applyVisibility()
    } catch (cause) {
      if (this.isConnectionActive(connectionGeneration)) await this.dispose()
      throw new Error(sanitizeMofaString(cause instanceof Error ? cause.message : String(cause)))
    }
  }

  private isConnectionActive(generation: number): boolean {
    return !this.disposed && this.connectionGeneration === generation
  }

  private assertConnectionActive(generation: number): void {
    if (!this.isConnectionActive(generation)) throw new Error('数字人连接已取消')
  }

  private handleSpeakStateChange(state: string, clientSpeakId?: string | number): void {
    const key = clientSpeakId === undefined || clientSpeakId === null ? undefined : String(clientSpeakId)
    if (state === 'speak_start') {
      if (key) this.activeSpeechId = key
      if (this.speechCompletion && !this.speechCompletion.clientSpeakId && key) this.speechCompletion.clientSpeakId = key
      return
    }
    const completion = this.speechCompletion
    if (!completion || completion.generation !== this.speechGeneration) return
    if (completion.clientSpeakId && key && completion.clientSpeakId !== key) return
    if (state === 'speak_end' || state === 'end') {
      this.finishSpeechCompletion()
      this.activeSpeechId = undefined
    } else if (state === 'speak_error' || state === 'error') {
      this.failSpeechCompletion(new Error('星云播报失败'))
    }
  }

  setVisibility(visible: boolean): void {
    const nextInvisible = !visible
    if (this.invisible === nextInvisible) return
    this.invisible = nextInvisible
    this.applyVisibility()
  }

  async speak(text: string, presentation?: AvatarPerformanceCue, options?: { flush?: boolean }): Promise<void> {
    const clean = text.trim()
    const flush = Boolean(options?.flush)
    if (!this.avatar || (!clean && !flush)) return
    if (clean) this.speechBuffer += clean
    while (true) {
      if (!this.speechBuffer.trim()) break
      const boundary = findSpeechBoundary(this.speechBuffer, flush)
      if (boundary < 0) break
      const segment = this.speechBuffer.slice(0, boundary).trim()
      this.speechBuffer = this.speechBuffer.slice(boundary).trimStart()
      if (!segment) continue
      if (this.pendingSpeech) {
        void this.dispatchSpeechSegment(this.pendingSpeech, false).catch((cause) => {
          debugMofa('SDK non-final speak failed', cause)
          this.status?.({ phase: 'error', message: cause instanceof Error ? cause.message : '数字人播报失败' })
        })
      }
      this.pendingSpeech = { text: segment, presentation }
    }
    if (!flush) return

    const finalSegment = this.pendingSpeech
    this.pendingSpeech = undefined
    if (!finalSegment) {
      if (!this.streamStarted) this.status?.({ phase: 'ready', message: '数字人已连接' })
      return
    }
    await this.dispatchSpeechSegment(finalSegment, true)
  }

  async interrupt(): Promise<void> {
    if (!this.avatar) return
    this.speechBuffer = ''
    this.pendingSpeech = undefined
    this.streamStarted = false
    this.speechGeneration += 1
    this.activeSpeechId = undefined
    this.finishSpeechCompletion()
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

  private async dispatchSpeechSegment(segment: { text: string; presentation?: AvatarPerformanceCue }, isEnd: boolean): Promise<void> {
    const generation = this.speechGeneration
    if (!this.avatar || generation !== this.speechGeneration) return
    const request = buildMofaSpeechRequest(segment.text, segment.presentation, { enableEmotion: this.emotionEnabled })
    const extra = Object.keys(request.extra).length ? request.extra : undefined
    const isStart = !this.streamStarted
    debugMofa('SDK speak dispatched', {
      isStart,
      isEnd,
      textLength: segment.text.length,
      hasExtra: Boolean(extra),
    })
    if (!isEnd) {
      this.avatar.speak(request.ssml, isStart, false, extra)
      this.streamStarted = true
      this.status?.({ phase: 'speaking', message: '数字人正在表达' })
      return
    }

    const completion = this.createSpeechCompletion(generation)
    this.speechCompletion = completion
    this.avatar.speak(request.ssml, isStart, true, extra)
    this.streamStarted = true
    this.status?.({ phase: 'speaking', message: '数字人正在表达' })
    try {
      await completion.promise
    } catch (cause) {
      if (generation === this.speechGeneration) {
        this.streamStarted = false
        this.activeSpeechId = undefined
      }
      debugMofa('SDK speak failed', { clientSpeakId: completion.clientSpeakId, cause })
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
      this.avatar?.interrupt('speak_timeout')
      completion.reject(new Error('星云播报超时'))
    }, 15_000)
    return completion
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

function findSpeechBoundary(value: string, flush: boolean): number {
  const punctuation = /[。！？!?；;\n]/g
  let match: RegExpExecArray | null
  while ((match = punctuation.exec(value))) return match.index + 1
  if (value.trim().length >= 16 || flush) return value.length
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

async function waitForStablePaint(): Promise<void> {
  await new Promise<void>((resolve) => window.requestAnimationFrame(() => window.requestAnimationFrame(() => resolve())))
}
