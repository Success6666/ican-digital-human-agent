import { buildRealtimeConfig, controlFrame } from './protocol'
import { RealtimeSocketClient } from './socket'
import type {
  RealtimeClientConfig,
  RealtimeConnectionState,
  RealtimeInboundEvent,
} from './types'

const READY_TIMEOUT_MS = 8_000

export interface RealtimeTransportHandlers {
  onState: (state: RealtimeConnectionState) => void
  onReady: (event: RealtimeInboundEvent) => void
  onEvent: (event: RealtimeInboundEvent) => void
  onError: (message: string) => void
}

/** WebSocket handshake, ready barrier, heartbeat and bounded reconnect. */
export class RealtimeTransport {
  private readonly sessionId: string
  private config: RealtimeClientConfig
  private readonly handlers: RealtimeTransportHandlers
  private socket?: RealtimeSocketClient
  private heartbeat?: ReturnType<typeof setInterval>
  private readyTimer?: ReturnType<typeof setTimeout>
  private readyPromise?: Promise<boolean>
  private readyResolve?: (ready: boolean) => void
  private ready = false
  private disposed = false

  constructor(sessionId: string, config: RealtimeClientConfig, handlers: RealtimeTransportHandlers) {
    this.sessionId = sessionId
    this.config = config
    this.handlers = handlers
  }

  mount(): void {
    if (this.disposed || this.socket) return
    this.socket = new RealtimeSocketClient({
      // The browser must stay on the authenticated same-origin gateway. Any
      // provider-specific media endpoint is handled by its runtime adapter.
      endpoint: this.config.endpoint,
      maxReconnectAttempts: 2,
      onState: (state) => this.handleSocketState(state),
      onOpen: () => this.handleOpen(),
      onClose: () => this.clearHeartbeat(),
      onError: (message) => this.handlers.onError(message),
      onMessage: (event) => this.handleInbound(event),
    })
    void this.socket.connect().catch(() => undefined)
  }

  async dispose(): Promise<void> {
    if (this.disposed) return
    this.disposed = true
    this.ready = false
    this.clearHeartbeat()
    this.resolveReady(false)
    this.socket?.close()
    this.socket = undefined
  }

  close(): void {
    this.ready = false
    this.clearHeartbeat()
    this.resolveReady(false)
    this.socket?.close()
    this.handlers.onState('closed')
  }

  async connect(): Promise<boolean> {
    if (this.disposed || !this.socket) return false
    if (this.ready) return true
    try {
      if (!this.socket.isOpen) await this.socket.connect()
      if (this.ready) return true
      return await this.waitForReady()
    } catch (cause) {
      this.handlers.onError(cause instanceof Error ? cause.message : '实时通道连接失败')
      return false
    }
  }

  get isReady(): boolean { return this.ready }
  get isOpen(): boolean { return Boolean(this.socket?.isOpen) }
  get bufferedAmount(): number { return this.socket?.bufferedAmount ?? 0 }
  get negotiatedConfig(): RealtimeClientConfig { return { ...this.config } }

  send(data: string | ArrayBuffer): boolean {
    if (!this.ready || !this.socket) return false
    return this.socket.send(data)
  }

  private handleSocketState(state: RealtimeConnectionState): void {
    this.ready = false
    this.handlers.onState(state === 'connected' ? 'connecting' : state)
    if (state !== 'connected') {
      this.clearHeartbeat()
      this.resolveReady(false)
    }
  }

  private handleOpen(): void {
    this.ready = false
    this.armReadyTimer()
    const sent = this.socket?.send(controlFrame('hello', {
      requestId: nextId('hello'), sessionId: this.sessionId, protocol: this.config.protocol,
    }))
    if (!sent) {
      this.resolveReady(false)
      this.socket?.close(4008, '握手发送失败')
    }
  }

  private handleInbound(event: RealtimeInboundEvent): void {
    const type = String(event.type ?? '').toLowerCase()
    if (event.sessionId && event.sessionId !== this.sessionId) return
    if (type === 'ping') {
      this.socket?.send(controlFrame('pong', {
        requestId: event.requestId ?? nextId('pong'), sessionId: this.sessionId, nonce: event.requestId,
      }))
      return
    }
    if (type === 'ready') {
      this.config = mergeNegotiatedConfig(this.config, event)
      this.ready = true
      this.resolveReady(true)
      this.handlers.onReady(event)
      this.startHeartbeat()
      return
    }
    this.handlers.onEvent(event)
  }

  private waitForReady(): Promise<boolean> {
    if (this.ready) return Promise.resolve(true)
    if (!this.readyPromise) {
      this.readyPromise = new Promise<boolean>((resolve) => { this.readyResolve = resolve })
      if (this.readyTimer === undefined) this.armReadyTimer()
    }
    return this.readyPromise
  }

  private armReadyTimer(): void {
    if (this.readyTimer !== undefined) clearTimeout(this.readyTimer)
    this.readyTimer = setTimeout(() => {
      if (this.disposed || this.ready) return
      this.resolveReady(false)
      this.socket?.close(4008, 'ready 握手超时')
    }, READY_TIMEOUT_MS)
  }

  private resolveReady(value: boolean): void {
    if (this.readyTimer !== undefined) clearTimeout(this.readyTimer)
    this.readyTimer = undefined
    this.readyResolve?.(value)
    this.readyResolve = undefined
    this.readyPromise = undefined
  }

  private startHeartbeat(): void {
    this.clearHeartbeat()
    this.heartbeat = setInterval(() => {
      if (this.ready) this.socket?.send(controlFrame('ping', { requestId: nextId('ping'), sessionId: this.sessionId }))
    }, Math.max(5_000, this.config.heartbeatMs))
  }

  private clearHeartbeat(): void {
    if (this.heartbeat !== undefined) clearInterval(this.heartbeat)
    this.heartbeat = undefined
  }
}

function mergeNegotiatedConfig(config: RealtimeClientConfig, event: RealtimeInboundEvent): RealtimeClientConfig {
  const format = event.audioFormat ?? {}
  const limits = event.limits ?? {}
  return {
    ...config,
    heartbeatMs: boundedInteger(event.heartbeatMs, config.heartbeatMs, 5_000, 300_000),
    codec: boundedText(format.codec, config.codec),
    sampleRate: boundedInteger(format.sampleRate, config.sampleRate, 8_000, 96_000),
    channels: boundedInteger(format.channels, config.channels, 1, 2) as 1 | 2,
    frameMs: boundedInteger(format.frameMs, config.frameMs, 10, 100),
    audioFrameBytes: boundedInteger(limits.audioFrameBytes, config.audioFrameBytes ?? 0, 2, 1_048_576) || config.audioFrameBytes,
    maxAudioFrameBytes: boundedInteger(limits.maxAudioFrameBytes, config.maxAudioFrameBytes ?? config.maxFrameBytes, 2, 1_048_576),
    maxAudioBufferBytes: boundedInteger(limits.maxAudioBufferBytes, config.maxAudioBufferBytes ?? 0, 2, 8 * 1024 * 1024) || config.maxAudioBufferBytes,
    maxFrameBytes: boundedInteger(limits.maxAudioFrameBytes ?? limits.audioFrameBytes, config.maxFrameBytes, 2, 1_048_576),
  }
}

function boundedInteger(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isInteger(parsed) && parsed >= min && parsed <= max ? parsed : fallback
}

function boundedText(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value.trim().slice(0, 64) : fallback
}

export function nextId(prefix: string): string {
  const random = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  return `${prefix}-${random}`.slice(0, 128)
}

export { buildRealtimeConfig }
