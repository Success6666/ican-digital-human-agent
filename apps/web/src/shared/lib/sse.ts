import type { ChatStreamEvent } from '../api/types'
import { API_BASE, getToken } from '../api/client'

export interface SseHandlers {
  onEvent: (event: ChatStreamEvent) => void
  onOpen?: () => void
}

export interface SseOptions {
  /** 单个 SSE 帧的最大字符数，避免异常上游造成浏览器内存膨胀。 */
  maxFrameChars?: number
}

function decodeEvent(block: string): ChatStreamEvent | null {
  const lines = block.split(/\r?\n/)
  let eventType = 'message'
  let eventId: string | undefined
  const data: string[] = []
  for (const line of lines) {
    if (!line || line.startsWith(':')) continue
    const separator = line.indexOf(':')
    const field = separator === -1 ? line : line.slice(0, separator)
    const value = separator === -1 ? '' : line.slice(separator + 1).trimStart()
    if (field === 'event') eventType = value
    if (field === 'id') eventId = value
    if (field === 'data') data.push(value)
  }
  if (data.length === 0) return null
  const raw = data.join('\n')
  try {
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { type: eventType, text: typeof parsed === 'string' ? parsed : raw, eventId }
    }
    const record = parsed as Record<string, unknown>
    const parsedEventId = record.eventId == null ? undefined : String(record.eventId)
    return { ...record, type: String(record.type ?? record.event ?? eventType), eventId: eventId ?? parsedEventId }
  } catch {
    return { type: eventType, text: raw, eventId }
  }
}

export async function streamSse(
  path: string,
  body: unknown,
  handlers: SseHandlers,
  signal?: AbortSignal,
  options: SseOptions = {},
): Promise<void> {
  const maxFrameChars = Math.max(8 * 1024, Math.floor(options.maxFrameChars ?? 512 * 1024))
  const token = getToken()
  const headers = new Headers({
    Accept: 'text/event-stream',
    'Content-Type': 'application/json',
    'X-Client': 'digital-human-agent-web',
  })
  if (token) {
    headers.set('satoken', token)
    headers.set('Authorization', `Bearer ${token}`)
  }
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new CustomEvent('auth:expired'))
    const text = await response.text().catch(() => '')
    throw new Error(text || `流式请求失败（${response.status}）`)
  }
  if (!response.body) throw new Error('服务端未返回流式响应')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let streamEnded = false
  try {
    handlers.onOpen?.()
    while (true) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop() ?? ''
      for (const block of blocks) {
        if (signal?.aborted) return
        if (block.length > maxFrameChars) throw new Error('流式事件过大，已停止接收')
        const event = decodeEvent(block)
        if (event) handlers.onEvent(event)
      }
      if (buffer.length > maxFrameChars) throw new Error('流式事件过大，已停止接收')
      if (done) {
        streamEnded = true
        break
      }
    }
    if (signal?.aborted) return
    if (buffer.length > maxFrameChars) throw new Error('流式事件过大，已停止接收')
    const tail = decodeEvent(buffer)
    if (tail) handlers.onEvent(tail)
  } finally {
    if (!streamEnded) {
      await reader.cancel().catch(() => undefined)
    }
    reader.releaseLock()
  }
}
