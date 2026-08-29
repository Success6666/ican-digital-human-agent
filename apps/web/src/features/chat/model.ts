import { useCallback, useEffect, useRef, useState } from 'react'
import type { AvatarSession, ChatStreamEvent, ToolCall } from '../../shared/api/types'
import { formatTime, sanitizeDisplayText } from '../../shared/lib/format'
import * as chatApi from './api'
import { markBusinessEvent, recoverableStreamMessage, streamFailureAction } from './streamRecovery'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  createdAt: string
  pending?: boolean
  traceId?: string
}

export interface TimelineItem {
  id: string
  type: 'start' | 'filler' | 'intent' | 'disclosure' | 'security' | 'rag' | 'tool' | 'provider' | 'performance' | 'delta' | 'done' | 'interrupted' | 'error' | 'info'
  title: string
  detail?: string
  createdAt: string
  seq?: number
}

const id = (prefix: string) => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

function eventText(event: ChatStreamEvent): string {
  const candidate = event.text ?? event.reply ?? event.delta ?? event.content
  return typeof candidate === 'string' ? candidate : ''
}

const intentLabels: Record<string, string> = {
  chat: '闲聊',
  knowledge: '知识问答',
  task: '任务处理',
  control: '系统控制',
  security: '安全请求',
}

function intentText(value: unknown): string {
  const key = String(value ?? '').toLowerCase()
  return intentLabels[key] ?? (key ? sanitizeDisplayText(key, 48) : '待识别')
}

function performanceText(event: ChatStreamEvent): string | undefined {
  const performance = event.performance
  if (!performance || typeof performance !== 'object') return undefined
  const expression = String((performance as Record<string, unknown>).expression ?? '').toLowerCase()
  const labels: Record<string, string> = {
    listening: '聆听',
    thinking: '思考',
    speaking: '表达',
    complete: '完成',
    interrupted: '已打断',
  }
  return expression ? `数字人状态：${labels[expression] ?? sanitizeDisplayText(expression, 32)}` : '数字人状态已更新'
}

function eventTool(event: ChatStreamEvent): ToolCall | undefined {
  if (event.toolCall && typeof event.toolCall === 'object') return event.toolCall as ToolCall
  if (event.tool && typeof event.tool === 'object') return event.tool as ToolCall
  return undefined
}

function eventTools(event: ChatStreamEvent): ToolCall[] {
  if (!Array.isArray(event.toolCalls)) return []
  return event.toolCalls.filter((item): item is ToolCall => Boolean(item && typeof item === 'object'))
}

function toolDetail(tool: ToolCall): string | undefined {
  if (tool.status === 'failed') return '工具执行失败'
  if (tool.status === 'running') return '工具执行中'
  if (typeof tool.durationMs === 'number' && Number.isFinite(tool.durationMs)) return `工具已完成 · ${Math.round(tool.durationMs)} ms`
  return '工具已返回结果'
}

export function useChat(session: AvatarSession | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [timeline, setTimeline] = useState<TimelineItem[]>([])
  const [isSending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    abortRef.current?.abort()
    setMessages([])
    setTimeline([])
    setError(null)
  }, [session?.sessionId])

  const addTimeline = useCallback((item: Omit<TimelineItem, 'id' | 'createdAt'>) => {
    setTimeline((current) => [...current, { ...item, id: id('event'), createdAt: new Date().toISOString() }])
  }, [])

  const updateAssistant = useCallback((messageId: string, patch: Partial<ChatMessage>) => {
    setMessages((current) => current.map((message) => message.id === messageId ? { ...message, ...patch } : message))
  }, [])

  const sendMessage = useCallback(async (value: string) => {
    const message = value.trim()
    if (!message || !session || isSending) return
    const sessionId = session.sessionId
    setError(null)
    setSending(true)
    const userMessage: ChatMessage = { id: id('user'), role: 'user', content: message, createdAt: new Date().toISOString() }
    const assistantId = id('assistant')
    const assistantMessage: ChatMessage = { id: assistantId, role: 'assistant', content: '', createdAt: new Date().toISOString(), pending: true }
    setMessages((current) => [...current, userMessage, assistantMessage])
    const controller = new AbortController()
    abortRef.current = controller
    let accumulated = ''
    let traceId: string | undefined
    let sawDone = false
    let executionStarted = false

    const onEvent = (event: ChatStreamEvent) => {
      const kind = String(event.type ?? 'message').toLowerCase()
      traceId = typeof event.traceId === 'string' ? event.traceId : traceId
      if (markBusinessEvent(kind)) executionStarted = true
      if (kind === 'start') {
        addTimeline({ type: 'start', title: 'Agent 开始处理', detail: performanceText(event) ?? '运行链路已启动', seq: event.seq })
      } else if (kind === 'filler') {
        const filler = eventText(event)
        addTimeline({ type: 'filler', title: '数字人正在思考', detail: filler ? sanitizeDisplayText(filler, 120) : performanceText(event), seq: event.seq })
      } else if (kind === 'intent') {
        addTimeline({ type: 'intent', title: '已识别用户意图', detail: `${intentText(event.intent)} · 置信度 ${confidenceText(event.confidence)}`, seq: event.seq })
      } else if (kind === 'tool_disclosure') {
        const names = disclosureNames(event.tools)
        addTimeline({ type: 'disclosure', title: '已规划工具调用', detail: names ? `计划使用：${names}` : '按需选择 MCP 工具', seq: event.seq })
      } else if (kind === 'security') {
        addTimeline({ type: 'security', title: event.blocked === true ? '已拦截不安全请求' : '安全检查通过', detail: event.blocked === true ? '已跳过知识检索与工具调用' : '输入未命中安全策略', seq: event.seq })
      } else if (kind === 'tool') {
        const tools = eventTools(event)
        const tool = eventTool(event)
        if (tools.length) {
          for (const call of tools) addTimeline({ type: 'tool', title: call.name ? `调用工具 · ${sanitizeDisplayText(call.name, 64)}` : '执行 MCP 工具', detail: toolDetail(call), seq: event.seq })
        } else {
          addTimeline({ type: 'tool', title: tool?.name ? `调用工具 · ${sanitizeDisplayText(tool.name, 64)}` : '执行 MCP 工具', detail: tool ? toolDetail(tool) : '工具事件已记录', seq: event.seq })
        }
      } else if (kind === 'rag') {
        const hitCount = typeof event.hitCount === 'number' ? event.hitCount : 0
        const degraded = event.degraded === true
        addTimeline({
          type: 'rag',
          title: degraded ? 'RAG 检索降级' : 'RAG 检索完成',
          detail: degraded ? '文档检索暂不可用，继续执行主链路' : `命中 ${hitCount} 个片段`,
          seq: event.seq,
        })
      } else if (kind === 'provider') {
        addTimeline({ type: 'provider', title: 'Provider 返回结果', detail: performanceText(event) ?? providerStatusText(event.status), seq: event.seq })
      } else if (kind === 'delta' || kind === 'message') {
        const chunk = eventText(event)
        if (chunk) {
          accumulated += chunk
          updateAssistant(assistantId, { content: accumulated, traceId })
          addTimeline({ type: 'delta', title: '收到增量响应', detail: `${chunk.length} 字符`, seq: event.seq })
        }
      } else if (kind === 'done') {
        sawDone = true
        const finalReply = eventText(event) || accumulated
        accumulated = finalReply
        updateAssistant(assistantId, { content: finalReply, pending: false, traceId })
        addTimeline({ type: 'done', title: '响应完成', detail: event.interrupted === true ? '本次响应已打断' : performanceText(event) ?? '运行链路已完成', seq: event.seq })
      } else if (kind === 'interrupted') {
        const interruptedText = eventText(event) || '本次响应已打断。'
        accumulated = accumulated || interruptedText
        updateAssistant(assistantId, { content: accumulated, pending: false, traceId })
        addTimeline({ type: 'interrupted', title: '已停止生成', detail: performanceText(event) ?? sanitizeDisplayText(interruptedText), seq: event.seq })
      } else if (kind === 'error') {
        throw new Error(sanitizeDisplayText(String(event.message || eventText(event) || 'Agent 返回错误')))
      }
    }

    try {
      await chatApi.streamChat({ sessionId, message }, onEvent, controller.signal)
      const action = streamFailureAction({ executionStarted, terminal: sawDone, aborted: controller.signal.aborted })
      if (action === 'fallback') {
        await completeWithSyncFallback()
      } else if (action === 'stopped') {
        updateAssistant(assistantId, { content: accumulated || '本次响应已停止。', pending: false, traceId })
        addTimeline({ type: 'info', title: '已停止生成' })
      } else if (!sawDone) {
        updateAssistant(assistantId, { content: accumulated || '服务端已结束响应。', pending: false, traceId })
        addTimeline({ type: 'done', title: '响应完成', detail: '运行链路已完成' })
      }
    } catch (cause) {
      const action = streamFailureAction({ executionStarted, terminal: sawDone, aborted: controller.signal.aborted })
      if (action === 'stopped') {
        updateAssistant(assistantId, { content: accumulated || '本次响应已停止。', pending: false, traceId })
        addTimeline({ type: 'info', title: '已停止生成' })
      } else if (action === 'fallback') {
        await completeWithSyncFallback(cause)
      } else if (action === 'recoverable') {
        const recoverable = recoverableStreamMessage(Boolean(accumulated))
        updateAssistant(assistantId, { content: accumulated || recoverable, pending: false, traceId })
        setError(recoverable)
        addTimeline({ type: 'error', title: '流式响应中断', detail: recoverable })
      } else {
        updateAssistant(assistantId, { content: accumulated || '服务端已结束响应。', pending: false, traceId })
      }
    } finally {
      abortRef.current = null
      setSending(false)
    }

    async function completeWithSyncFallback(streamCause?: unknown) {
      try {
        addTimeline({ type: 'info', title: '流式连接未开始执行，切换同步响应' })
        const response = await chatApi.sendChat({ sessionId, message })
        updateAssistant(assistantId, { content: response.reply, pending: false, traceId: response.traceId })
        for (const tool of response.toolCalls ?? []) {
          addTimeline({ type: 'tool', title: tool.name ? `调用工具 · ${sanitizeDisplayText(tool.name, 64)}` : '执行 MCP 工具', detail: toolDetail(tool) })
        }
        addTimeline({ type: 'done', title: '同步响应完成', detail: '运行链路已完成' })
      } catch (fallbackCause) {
        const messageText = sanitizeDisplayText(fallbackCause instanceof Error ? fallbackCause.message : (streamCause instanceof Error ? streamCause.message : '请求失败'))
        updateAssistant(assistantId, { content: '暂时无法获得 Agent 响应。', pending: false })
        setError(messageText)
        addTimeline({ type: 'error', title: '响应失败', detail: messageText })
      }
    }
  }, [addTimeline, isSending, session, updateAssistant])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    if (session) void chatApi.interruptSession(session.sessionId).catch(() => undefined)
  }, [session])
  const clear = useCallback(() => {
    const currentSession = session
    abortRef.current?.abort()
    if (currentSession) void chatApi.interruptSession(currentSession.sessionId).catch(() => undefined)
    setMessages([])
    setTimeline([])
    setError(null)
  }, [session])

  return { messages, timeline, isSending, error, sendMessage, stop, clear, formatTime }
}

function confidenceText(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  const normalized = value > 1 ? value : value * 100
  return `${Math.max(0, Math.min(100, normalized)).toFixed(0)}%`
}

function disclosureNames(value: unknown): string | undefined {
  if (!Array.isArray(value)) return undefined
  const names = value.map((item) => {
    if (!item || typeof item !== 'object') return ''
    const record = item as Record<string, unknown>
    return sanitizeDisplayText(String(record.label ?? record.name ?? ''), 48)
  }).filter(Boolean).slice(0, 3)
  return names.length ? names.join('、') : undefined
}

function providerStatusText(value: unknown): string | undefined {
  const status = String(value ?? '').toLowerCase()
  if (status === 'ok' || status === 'success' || status === 'completed') return 'Provider 已完成'
  if (status === 'error' || status === 'failed') return 'Provider 返回异常'
  return status ? `Provider 状态：${sanitizeDisplayText(status, 32)}` : undefined
}
