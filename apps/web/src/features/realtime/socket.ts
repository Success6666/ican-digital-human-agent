import { decodeRealtimeMessage } from './protocol'
import type { RealtimeConnectionState, RealtimeSocketOptions } from './types'

const DEFAULT_HANDSHAKE_TIMEOUT = 8_000
const DEFAULT_RECONNECTS = 2

/** Small browser WebSocket wrapper with bounded reconnects and one writer. */
export class RealtimeSocketClient {
  private readonly options: RealtimeSocketOptions
  private socket: WebSocket | null = null
  private pendingConnect: Promise<void> | null = null
  private pendingResolve: (() => void) | null = null
  private pendingReject: ((error: Error) => void) | null = null
  private handshakeTimer: ReturnType<typeof setTimeout> | undefined
  private reconnectTimer: ReturnType<typeof setTimeout> | undefined
  private reconnectScheduled = false
  private reconnectAttempt = 0
  private generation = 0
  private manuallyClosed = false

  constructor(options: RealtimeSocketOptions) {
    this.options = options
  }

  get isOpen(): boolean {
    return this.socket?.readyState === 1
  }

  get bufferedAmount(): number {
    return this.socket?.bufferedAmount ?? 0
  }

  connect(): Promise<void> {
    if (this.isOpen) return Promise.resolve()
    if (this.pendingConnect) return this.pendingConnect
    this.manuallyClosed = false
    // A user-initiated reconnect supersedes an already scheduled backoff;
    // otherwise the timer could open a second socket behind this one.
    if (this.reconnectTimer !== undefined) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = undefined
    this.reconnectScheduled = false
    this.notifyState('connecting')
    this.pendingConnect = new Promise<void>((resolve, reject) => {
      this.pendingResolve = resolve
      this.pendingReject = reject
      this.openSocket()
    })
    return this.pendingConnect
  }

  close(code = 1000, reason = '客户端关闭'): void {
    this.manuallyClosed = true
    this.clearTimers()
    this.rejectPending(new Error('实时通道已关闭'))
    const socket = this.socket
    this.socket = null
    this.generation += 1
    if (socket && socket.readyState !== 3) socket.close(code, reason)
    this.notifyState('closed')
  }

  send(data: string | ArrayBuffer): boolean {
    const socket = this.socket
    if (!socket || socket.readyState !== 1) return false
    try {
      socket.send(data)
      return true
    } catch (cause) {
      this.options.onError?.(cause instanceof Error ? cause.message : '实时消息发送失败')
      return false
    }
  }

  private openSocket(): void {
    const generation = ++this.generation
    let socket: WebSocket
    try {
      socket = new WebSocket(this.options.endpoint, this.options.protocols)
      socket.binaryType = 'arraybuffer'
    } catch (cause) {
      this.failConnect(generation, cause instanceof Error ? cause : new Error('浏览器不支持 WebSocket'))
      return
    }
    this.socket = socket
    let opened = false
    const timeout = this.options.handshakeTimeoutMs ?? DEFAULT_HANDSHAKE_TIMEOUT
    this.handshakeTimer = setTimeout(() => {
      if (generation !== this.generation || opened) return
      try { socket.close(4008, '握手超时') } catch { /* best effort */ }
      this.failConnect(generation, new Error('实时通道连接超时'))
    }, Math.max(1_000, timeout))
    socket.onopen = () => {
      if (generation !== this.generation) return
      opened = true
      this.clearHandshakeTimer()
      this.reconnectScheduled = false
      this.reconnectAttempt = 0
      this.resolvePending()
      this.notifyState('connected')
      this.options.onOpen?.()
    }
    socket.onmessage = (event) => {
      if (generation !== this.generation) return
      void decodeRealtimeMessage(event.data).then((message) => {
        if (message) this.options.onMessage?.(message)
      })
    }
    socket.onerror = () => {
      if (generation === this.generation) this.options.onError?.('实时通道网络异常')
    }
    socket.onclose = (event) => {
      if (generation !== this.generation) return
      this.clearHandshakeTimer()
      this.socket = null
      if (!opened) this.rejectPending(new Error('实时通道连接失败'))
      this.options.onClose?.(event)
      if (!this.manuallyClosed && this.reconnectAttempt < (this.options.maxReconnectAttempts ?? DEFAULT_RECONNECTS)) {
        this.scheduleReconnect()
      } else {
        this.notifyState(this.manuallyClosed ? 'closed' : 'error')
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectScheduled || this.reconnectTimer !== undefined) return
    this.reconnectAttempt += 1
    const delay = Math.min(2_000, 250 * (2 ** (this.reconnectAttempt - 1)))
    this.notifyState('reconnecting')
    this.reconnectScheduled = true
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined
      this.reconnectScheduled = false
      if (!this.manuallyClosed) this.openSocket()
    }, delay)
  }

  private failConnect(generation: number, error: Error): void {
    if (generation !== this.generation) return
    this.clearHandshakeTimer()
    this.options.onError?.(error.message)
    this.rejectPending(error)
    if (!this.manuallyClosed && this.reconnectAttempt < (this.options.maxReconnectAttempts ?? DEFAULT_RECONNECTS)) this.scheduleReconnect()
    else this.notifyState('error')
  }

  private resolvePending(): void {
    this.pendingResolve?.()
    this.pendingResolve = null
    this.pendingReject = null
    this.pendingConnect = null
  }

  private rejectPending(error: Error): void {
    this.pendingReject?.(error)
    this.pendingResolve = null
    this.pendingReject = null
    this.pendingConnect = null
  }

  private clearHandshakeTimer(): void {
    if (this.handshakeTimer !== undefined) clearTimeout(this.handshakeTimer)
    this.handshakeTimer = undefined
  }

  private clearTimers(): void {
    this.clearHandshakeTimer()
    if (this.reconnectTimer !== undefined) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = undefined
    this.reconnectScheduled = false
  }

  private notifyState(state: RealtimeConnectionState): void {
    this.options.onState?.(state)
  }
}
