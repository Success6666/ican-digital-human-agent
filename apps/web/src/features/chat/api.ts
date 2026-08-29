import { api } from '../../shared/api/client'
import { streamSse } from '../../shared/lib/sse'
import type { ChatRequest, ChatResponse, ChatStreamEvent } from '../../shared/api/types'

export async function sendChat(request: ChatRequest): Promise<ChatResponse> {
  const response = await api.post<ChatResponse>('/chat', request)
  return {
    reply: response.reply ?? '',
    traceId: response.traceId,
    toolCalls: response.toolCalls ?? [],
  }
}

export function streamChat(
  request: ChatRequest,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamSse('/chat/stream', request, { onEvent }, signal)
}

export async function interruptSession(sessionId: string): Promise<void> {
  await api.post(`/sessions/${encodeURIComponent(sessionId)}/interrupt`)
}
