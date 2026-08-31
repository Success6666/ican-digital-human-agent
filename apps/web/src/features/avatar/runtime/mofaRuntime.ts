import type { AvatarClientParams } from '../../../shared/api/types'
import type { AvatarPerformanceCue } from '../../../shared/api/types'
import type { AvatarRuntimeStatus, BrowserAvatarRuntime } from './browserRuntime'
import { loadExternalScript } from './scriptLoader'

interface XmovAvatarInstance {
  init(options?: Record<string, unknown>): Promise<void>
  speak(text: string, isStart?: boolean, isEnd?: boolean, extra?: Record<string, unknown>): Promise<void> | void
  stop(): Promise<void> | void
  destroy(reason?: string): Promise<void> | void
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

export class MofaBrowserRuntime implements BrowserAvatarRuntime {
  private avatar?: XmovAvatarInstance
  private status?: (status: AvatarRuntimeStatus) => void

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
    let markRendered!: () => void
    const firstFrame = new Promise<void>((resolve) => { markRendered = resolve })
    let rendered = false
    const markReady = () => {
      if (rendered) return
      rendered = true
      markRendered()
      onStatus({ phase: 'ready', progress: 100, message: '数字人已连接' })
    }

    this.avatar = new window.XmovAvatar({
      containerId: `#${containerId}`,
      appId: config.appId,
      appSecret: config.appSecret,
      headers: { Authorization: config.authorization },
      enableDebugger: false,
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
        if (detail) onStatus({ phase: 'error', message: `星云运行时：${detail}` })
      },
      onStartSessionWarning: (message: unknown) => {
        const detail = sdkMessage(message)
        if (detail) {
          console.warn('[Mofa Runtime] session warning', message)
          onStatus({ phase: 'loading', progress: 85, message: detail })
        }
      },
      onRenderChange: (state: unknown) => {
        if (String(state).toLowerCase().includes('render')) markReady()
      },
      onStatusChange: (state: unknown) => {
        const normalized = String(state).toLowerCase()
        if (normalized.includes('visible') || normalized.includes('online')) markReady()
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
    await withTimeout(Promise.race([initPromise, firstFrame]), 60_000)
    markReady()
  }

  async speak(text: string, presentation?: AvatarPerformanceCue): Promise<void> {
    const clean = text.trim()
    if (!clean || !this.avatar) return
    this.status?.({ phase: 'speaking', message: '数字人正在表达' })
    // Xingyun's browser SDK accepts plain text for its TTS queue. SSML is not
    // consistently supported across SDK versions and can leave the canvas in
    // an idle/static state without surfacing a useful error.
    await this.avatar.speak(clean, true, true, presentation ? { presentation } : {})
    this.status?.({ phase: 'ready', message: '数字人已连接' })
  }

  async interrupt(): Promise<void> {
    if (!this.avatar) return
    await this.avatar.stop()
    this.status?.({ phase: 'ready', message: '已停止上一轮表达' })
  }

  async dispose(): Promise<void> {
    const current = this.avatar
    this.avatar = undefined
    this.status = undefined
    if (!current) return
    try { await current.stop() } catch { /* SDK teardown remains best effort. */ }
    try { await current.destroy('component_unmounted') } catch { /* Host removal is the final cleanup boundary. */ }
  }
}

function requiredConfig(params: AvatarClientParams) {
  const values = {
    sdkUrl: params.sdkUrl, cryptoUrl: params.cryptoUrl, gatewayServer: params.gatewayServer,
    appId: params.appId, appSecret: params.appSecret, authorization: params.authorization,
    dataSource: params.dataSource, customId: params.customId,
  }
  for (const [name, value] of Object.entries(values)) {
    if (name === 'dataSource' || name === 'customId') continue
    if (!value) throw new Error(`魔珐数字人缺少 ${name} 配置`)
  }
  return values as Record<keyof typeof values, string>
}

function ensureContainerId(host: HTMLElement): string {
  if (!host.id) host.id = `mofa-avatar-${crypto.randomUUID()}`
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

async function withTimeout<T>(operation: Promise<T>, timeoutMs: number): Promise<T> {
  let timer = 0
  const timeout = new Promise<never>((_, reject) => {
    timer = window.setTimeout(() => reject(new Error('数字人初始化超时')), timeoutMs)
  })
  try { return await Promise.race([operation, timeout]) } finally { window.clearTimeout(timer) }
}
