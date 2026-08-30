import type { ChatStreamEvent } from '../../shared/api/types'

const TERMINAL_EVENTS = new Set(['done'])
const INTERRUPTED_EVENT = 'interrupted'

export interface StreamEventGateOptions {
  /** 防止断线重放或异常 Provider 导致客户端集合无界增长。 */
  maxEventIds?: number
}

/**
 * 按 run、序号和事件标识保护一条浏览器流。
 *
 * HTTP 本身保证单连接字节顺序，但重连、代理重放或上游重复写入仍可能
 * 让同一事件抵达多次。网关错误帧可能没有 runId，因此 error 事件允许在
 * 已锁定 run 后继续接收；其它缺少 runId 的事件会被丢弃，避免旧 run 污染。
 */
export class StreamEventGate {
  private readonly maxEventIds: number
  private readonly eventIds = new Set<string>()
  private runIdValue?: string
  private lastSequence?: number
  private interrupted = false
  private closing = false
  private terminal = false

  constructor(expectedRunId?: string, options: StreamEventGateOptions = {}) {
    this.runIdValue = normalize(expectedRunId)
    this.maxEventIds = Math.max(16, Math.floor(options.maxEventIds ?? 512))
  }

  get runId(): string | undefined {
    return this.runIdValue
  }

  /** 返回规范化后的事件；返回 null 表示重复、迟到或属于其它 run。 */
  accept(event: ChatStreamEvent): ChatStreamEvent | null {
    const kind = normalizeKind(event.type)
    if (this.terminal) return null
    if (this.interrupted && kind !== 'done' && kind !== 'error') return null
    if (this.closing && kind !== 'done' && kind !== 'error') return null

    const eventRunId = normalize(event.runId)
    if (this.runIdValue) {
      if (eventRunId && eventRunId !== this.runIdValue) return null
      // 网关在传输失败时可能只能写出没有 runId 的 error 帧。
      if (!eventRunId && kind !== 'error') return null
    } else if (eventRunId) {
      this.runIdValue = eventRunId
    }

    const eventId = normalize(event.eventId)
    if (eventId && this.eventIds.has(eventId)) return null

    const sequence = finiteSequence(event.seq)
    if (sequence !== undefined && this.lastSequence !== undefined && sequence <= this.lastSequence) {
      return null
    }

    if (eventId) this.remember(eventId)
    if (sequence !== undefined) this.lastSequence = sequence
    if (kind === INTERRUPTED_EVENT) this.interrupted = true
    if (kind === 'error') this.closing = true
    if (TERMINAL_EVENTS.has(kind)) this.terminal = true

    const normalizedRunId = eventRunId ?? this.runIdValue
    return normalizedRunId ? { ...event, runId: normalizedRunId } : event
  }

  private remember(eventId: string): void {
    this.eventIds.add(eventId)
    while (this.eventIds.size > this.maxEventIds) {
      const oldest = this.eventIds.values().next().value as string | undefined
      if (oldest === undefined) break
      this.eventIds.delete(oldest)
    }
  }
}

function normalize(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = value.trim()
  return normalized || undefined
}

function normalizeKind(value: unknown): string {
  return String(value ?? 'message').trim().toLowerCase()
}

function finiteSequence(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) return undefined
  return value
}
