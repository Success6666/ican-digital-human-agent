import type { AvatarClientParams } from '../../../shared/api/types'
import type { AvatarPerformanceCue } from '../../../shared/api/types'
import type { AvatarRuntimeStatus, BrowserAvatarRuntime } from './browserRuntime'
import { buildMofaSpeechRequest } from './mofaSpeech'
import { createRuntimeId } from './runtimeId'
import { loadExternalScript } from './scriptLoader'

interface XmovAvatarInstance {
  init(options?: Record<string, unknown>): Promise<void>
  speak(text: string, isStart?: boolean, isEnd?: boolean, extra?: Record<string, unknown>): Promise<void> | void
  interrupt(type: string): number
  stop(): Promise<void> | void
  destroy(reason?: string): Promise<void> | void
  switchInvisibleMode(): number | void
  changeAvatarVisible(visible: boolean): void
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
  dataSource?: string
  customId?: string
}

export class MofaBrowserRuntime implements BrowserAvatarRuntime {
  private avatar?: XmovAvatarInstance
  private status?: (status: AvatarRuntimeStatus) => void
  private speechBuffer = ''
  private speechQueue: Array<{ text: string; presentation?: AvatarPerformanceCue }> = []
  private speechWorker?: Promise<void>
  private speechGeneration = 0
  private speechWaiters = new Map<string, { resolve: () => void; reject: (error: Error) => void }>()
  private speechFlushRequested = false
  private streamStarted = false
  private invisible = false

  async connect(host: HTMLElement, params: AvatarClientParams, onStatus: (status: AvatarRuntimeStatus) => void): Promise<void> {
    this.status = onStatus
    const config = requiredConfig(params)
    onStatus({ phase: 'loading', progress: 0, message: '正在加载数字人运行时' })
    await loadExternalScript(config.cryptoUrl, () => Boolean(window.CryptoJS))
    window.CryptoJSTest = window.CryptoJS
    await loadExternalScript(config.sdkUrl, () => Boolean(window.XmovAvatar))
    if (!window.XmovAvatar) throw new Error('魔珐数字人 SDK 不可用')

    const containerId = ensureContainerId(host)
    const gateway = new URL(config.gatewayServer)
    if (config.dataSource) gateway.searchParams.set('data_source', config.dataSource)
    if (config.customId) gateway.searchParams.set('custom_id', config.customId)
    const width = Math.max(320, Math.round(host.clientWidth || 960))
    const height = Math.max(320, Math.round(host.clientHeight || 720))
    // The SDK renders a 1080x1920 portrait canvas. Fit the complete avatar
    // inside the conversation stage instead of clipping the head at the top.
    const avatarScale = Math.min(0.36, Math.max(0.28, (height / 1920) * 0.98))
    let signalFirstFrame!: () => void
    const firstFrame = new Promise<void>((resolve) => { signalFirstFrame = resolve })
    let initialized = false
    let rendered = false
    const markReady = () => {
      signalFirstFrame()
      if (!initialized) return
      if (rendered) return
      rendered = true
      onStatus({ phase: 'ready', progress: 100, message: '数字人已连接' })
    }

    const headers = config.authorization ? { Authorization: config.authorization } : undefined
    this.avatar = new window.XmovAvatar({
      containerId: `#${containerId}`,
      appId: config.appId,
      appSecret: config.appSecret,
      ...(headers ? { headers } : {}),
      enableDebugger: false,
      enableClientInterrupt: true,
      gatewayServer: gateway.toString(),
      config: {
        raw_audio: false,
        walk_version: 3,
        framedata_proto_version: 2,
        layout: {
          avatar: { h_align: 'center', v_align: 'bottom', scale: avatarScale },
          container: { size: [width, height] },
        },
      },
      onMessage: (message: { code?: string | number; message?: string }) => {
        const detail = sdkMessage(message)
        const networkState = sdkNetworkState(message)
        if (networkState === 'reconnecting') {
          onStatus({ phase: 'loading', progress: 90, message: '网络波动，正在自动重连' })
          return
        }
        if (networkState === 'online') {
          markReady()
          return
        }
        if (isSpeechOverlapWarning(detail)) {
          console.warn('[Mofa Runtime] recovered overlapping speech boundary', message)
          onStatus({ phase: 'speaking', progress: 100, message: '数字人正在表达' })
          return
        }
        if (detail) onStatus({ phase: 'error', message: `星云运行时：${detail}` })
      },
      onStartSessionWarning: (message: unknown) => {
        const detail = sdkMessage(message)
        if (detail) {
          console.warn('[Mofa Runtime] session warning', message)
          if (isSpeechOverlapWarning(detail)) {
            // The SDK already performs a client-side fallback interrupt for
            // an overlapping speak_start. Keep the canvas usable and let the
            // serialized worker continue instead of replacing it with an
            // error overlay.
            onStatus({ phase: 'ready', progress: 100, message: '数字人已连接，正在恢复表达' })
            return
          }
          onStatus({ phase: 'loading', progress: 85, message: detail })
        }
      },
      onSpeakStateChange: (state: string, clientSpeakId?: string) => {
        if (!clientSpeakId) return
        const waiter = this.speechWaiters.get(clientSpeakId)
        if (!waiter) return
        if (state === 'speak_end') {
          this.speechWaiters.delete(clientSpeakId)
          waiter.resolve()
        } else if (state === 'speak_error') {
          this.speechWaiters.delete(clientSpeakId)
          waiter.reject(new Error('星云播报失败'))
        }
      },
      onRenderChange: (state: unknown) => {
        if (String(state).toLowerCase().includes('render')) markReady()
      },
      onStatusChange: (state: unknown) => {
        const normalized = normalizeSdkStatus(state)
        if (normalized === 'ready') markReady()
        if (normalized === 'reconnecting') onStatus({ phase: 'loading', progress: 90, message: '数字人连接恢复中' })
        if (normalized === 'closed') onStatus({ phase: 'error', message: '数字人连接已断开，请重新连接' })
      },
    })

    const initPromise = Promise.resolve(this.avatar.init({
      onDownloadProgress: (progress: number) => {
        const normalized = progress <= 1 ? progress * 100 : progress
        const value = Math.max(0, Math.min(100, Math.round(normalized)))
        if (rendered) return
        onStatus({ phase: 'loading', progress: value, message: '正在加载数字人资源' })
      },
      onClose: () => onStatus({ phase: 'error', message: '数字人连接已断开，请重新连接' }),
    }))
    await withTimeout(initPromise, 60_000)
    initialized = true
    await Promise.race([firstFrame, delay(2_000)])
    await waitForStablePaint()
    markReady()
    if (this.invisible) this.applyVisibility()
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
    if (flush) this.speechFlushRequested = true
    if (clean) this.speechBuffer += clean
    while (true) {
      if (!this.speechBuffer.trim()) break
      const boundary = findSpeechBoundary(this.speechBuffer, flush)
      if (boundary < 0) break
      const segment = this.speechBuffer.slice(0, boundary).trim()
      this.speechBuffer = this.speechBuffer.slice(boundary).trimStart()
      if (segment) this.speechQueue.push({ text: segment, presentation })
    }
    if (!this.speechQueue.length) return
    await this.ensureSpeechWorker()
  }

  async interrupt(): Promise<void> {
    if (!this.avatar) return
    this.speechBuffer = ''
    this.speechQueue = []
    this.speechFlushRequested = false
    this.streamStarted = false
    this.speechGeneration += 1
    for (const waiter of this.speechWaiters.values()) waiter.resolve()
    this.speechWaiters.clear()
    this.avatar.interrupt('user_speaking')
    this.status?.({ phase: 'ready', message: '已停止上一轮表达' })
  }

  async dispose(): Promise<void> {
    this.speechBuffer = ''
    this.speechQueue = []
    this.speechFlushRequested = false
    this.streamStarted = false
    this.speechGeneration += 1
    for (const waiter of this.speechWaiters.values()) waiter.resolve()
    this.speechWaiters.clear()
    const current = this.avatar
    this.avatar = undefined
    this.status = undefined
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

  private async consumeSpeechQueue(): Promise<void> {
    const generation = this.speechGeneration
    while (this.speechQueue.length && this.avatar) {
      if (generation !== this.speechGeneration) return
      const next = this.speechQueue.shift()
      if (!next) continue
      const isEnd = this.speechFlushRequested && this.speechQueue.length === 0 && !this.speechBuffer.trim()
      const isStart = !this.streamStarted
      this.status?.({ phase: 'speaking', message: '数字人正在表达' })
      await this.speakChunk(next.text, next.presentation, generation, isStart, isEnd)
      this.streamStarted = !isEnd
      if (isEnd) this.speechFlushRequested = false
    }
    // A flush may arrive while the last non-final chunk is already playing.
    // That chunk cannot be retroactively marked isEnd=true; once its own
    // speak_end arrives, close the local turn so the next response starts a
    // fresh SDK stream instead of inheriting stale state.
    if (this.speechFlushRequested && !this.speechQueue.length && !this.speechBuffer.trim()) {
      this.speechFlushRequested = false
      this.streamStarted = false
    }
    if (!this.streamStarted) this.status?.({ phase: 'ready', message: '数字人已连接' })
  }

  private ensureSpeechWorker(): Promise<void> {
    if (this.speechWorker) return this.speechWorker
    const worker = this.consumeSpeechQueue()
      .catch((cause) => {
        this.speechQueue = []
        this.status?.({ phase: 'error', message: cause instanceof Error ? cause.message : '数字人播报失败' })
      })
      .finally(() => {
        if (this.speechWorker === worker) this.speechWorker = undefined
        if (this.avatar && this.speechQueue.length && this.canDrainSpeechQueue()) void this.ensureSpeechWorker()
      })
    this.speechWorker = worker
    return worker
  }

  private canDrainSpeechQueue(): boolean {
    return this.speechFlushRequested || this.speechQueue.length > 1 || Boolean(this.speechBuffer.trim())
  }

  private async speakChunk(text: string, presentation: AvatarPerformanceCue | undefined, generation: number, isStart: boolean, isEnd: boolean): Promise<void> {
    if (!this.avatar || generation !== this.speechGeneration) return
    const request = buildMofaSpeechRequest(text, presentation)
    const clientSpeakId = createRuntimeId()
    const extra = { client_speak_id: clientSpeakId, ...request.extra }
    let completion: Promise<void>
    let timer = 0
    // Every chunk must wait for its own speak_end. Sending the next chunk
    // before that callback lets the SDK issue a new speak_start and replace
    // audio that is still playing, which causes fast streams to skip text.
    completion = new Promise<void>((resolve, reject) => {
      this.speechWaiters.set(clientSpeakId, { resolve, reject })
      timer = window.setTimeout(() => {
        this.speechWaiters.delete(clientSpeakId)
        if (generation === this.speechGeneration) this.avatar?.interrupt('speak_timeout')
        reject(new Error(`星云播报超时${isEnd ? '' : '，已停止后续分段'}`))
      }, 15_000)
    })
    try {
      await Promise.resolve(this.avatar.speak(request.ssml, isStart, isEnd, extra))
      await completion
    } finally {
      window.clearTimeout(timer)
      this.speechWaiters.delete(clientSpeakId)
    }
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
    dataSource: params.dataSource, customId: params.customId,
  }
  for (const [name, value] of Object.entries(values)) {
    if (name === 'authorization' || name === 'dataSource' || name === 'customId') continue
    if (!value) throw new Error(`魔珐数字人缺少 ${name} 配置`)
  }
  return values as MofaRuntimeConfig
}

function ensureContainerId(host: HTMLElement): string {
  if (!host.id) host.id = `mofa-avatar-${createRuntimeId()}`
  return host.id
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
  await delay(600)
  await new Promise<void>((resolve) => window.requestAnimationFrame(() => window.requestAnimationFrame(() => resolve())))
}
