import { useCallback, useEffect, useRef, useState } from 'react'
import type { AvatarSession, ChatStreamEvent } from '../../shared/api/types'
import { formatTime, sanitizeDisplayText } from '../../shared/lib/format'
import * as chatApi from './api'
import { markBusinessEvent, recoverableStreamMessage, streamFailureAction } from './streamRecovery'
import {
  confidenceText,
  disclosureNames,
  eventText,
  eventTool,
  eventTools,
  intentText,
  performanceText,
  providerStatusText,
  toolDetail,
} from './streamPresentation'

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

export function useChat(session: AvatarSession | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [timeline, setTimeline] = useState<TimelineItem[]>([])
  const [isSending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const turnRevisionRef = useRef(0)
  const activeSessionIdRef = useRef<string | null>(null)
  const activeRunIdRef = useRef<string | null>(null)
  const interruptRef = useRef<{ sessionId: string; runId?: string; promise: Promise<void> } | null>(null)

  const requestInterrupt = useCallback((sessionId: string, runId?: string): Promise<void> => {
    const current = interruptRef.current
    if (current?.sessionId === sessionId && current.runId === runId) return current.promise
    const promise = chatApi.interruptSession(sessionId, runId).catch(() => undefined)
    interruptRef.current = { sessionId, runId, promise }
    void promise.then(() => {
      if (interruptRef.current?.promise === promise) interruptRef.current = null
    })
    return promise
  }, [])

  useEffect(() => {
    const previousSessionId = activeSessionIdRef.current
    const previousRunId = activeRunIdRef.current ?? undefined
    turnRevisionRef.current += 1
    abortRef.current?.abort()
    if (previousSessionId && previousSessionId !== (session?.sessionId ?? null)) {
      void requestInterrupt(previousSessionId, previousRunId)
    }
    abortRef.current = null
    activeSessionIdRef.current = session?.sessionId ?? null
    activeRunIdRef.current = null
    setSending(false)
    setMessages([])
    setTimeline([])
    setError(null)

    return () => {
      const currentSessionId = activeSessionIdRef.current
      const currentRunId = activeRunIdRef.current ?? undefined
      const hasActiveRun = Boolean(abortRef.current || currentRunId)
      turnRevisionRef.current += 1
      abortRef.current?.abort()
      if (hasActiveRun && currentSessionId) {
        void requestInterrupt(currentSessionId, currentRunId)
      }
    }
  }, [requestInterrupt, session?.sessionId])

  const addTimeline = useCallback((item: Omit<TimelineItem, 'id' | 'createdAt'>) => {
    setTimeline((current) => [...current, { ...item, id: id('event'), createdAt: new Date().toISOString() }])
  }, [])

  const updateAssistant = useCallback((messageId: string, patch: Partial<ChatMessage>) => {
    setMessages((current) => current.map((message) => message.id === messageId ? { ...message, ...patch } : message))
  }, [])

  const sendMessage = useCallback(async (value: string) => {
    const message = value.trim()
    if (!message || !session) return
    const sessionId = session.sessionId
    const turnRevision = ++turnRevisionRef.current
    const previousController = abortRef.current
    const previousRunId = activeRunIdRef.current ?? undefined
    activeSessionIdRef.current = sessionId
    if (previousController) {
      setMessages((current) => current.map((message) => message.pending
        ? { ...message, pending: false, content: message.content || '本次响应已打断。' }
        : message))
      addTimeline({ type: 'interrupted', title: '已切换新指令', detail: '上一轮响应已停止，正在处理最新输入' })
    }
    previousController?.abort()
    const pendingInterrupt = previousController ? requestInterrupt(sessionId, previousRunId) : null
    activeRunIdRef.current = null
    if (pendingInterrupt) {
      await pendingInterrupt
      if (turnRevisionRef.current !== turnRevision) return
    }
    const isCurrentTurn = () => turnRevisionRef.current === turnRevision
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
      if (!isCurrentTurn()) return
      const eventRunId = typeof event.runId === 'string' ? event.runId : undefined
      if (eventRunId && activeRunIdRef.current && eventRunId !== activeRunIdRef.current) return
      const kind = String(event.type ?? 'message').toLowerCase()
      if (kind === 'start' && eventRunId) activeRunIdRef.current = eventRunId
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
      if (!isCurrentTurn()) return
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
      if (!isCurrentTurn()) return
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
      if (isCurrentTurn()) {
        abortRef.current = null
        setSending(false)
      }
    }

    async function completeWithSyncFallback(streamCause?: unknown) {
      if (!isCurrentTurn()) return
      try {
        addTimeline({ type: 'info', title: '流式连接未开始执行，切换同步响应' })
        const response = await chatApi.sendChat({ sessionId, message })
        if (!isCurrentTurn()) return
        if (response.runId) activeRunIdRef.current = response.runId
        updateAssistant(assistantId, { content: response.reply, pending: false, traceId: response.traceId })
        for (const tool of response.toolCalls ?? []) {
          addTimeline({ type: 'tool', title: tool.name ? `调用工具 · ${sanitizeDisplayText(tool.name, 64)}` : '执行 MCP 工具', detail: toolDetail(tool) })
        }
        addTimeline({ type: 'done', title: '同步响应完成', detail: '运行链路已完成' })
      } catch (fallbackCause) {
        if (!isCurrentTurn()) return
        const messageText = sanitizeDisplayText(fallbackCause instanceof Error ? fallbackCause.message : (streamCause instanceof Error ? streamCause.message : '请求失败'))
        updateAssistant(assistantId, { content: '暂时无法获得 Agent 响应。', pending: false })
        setError(messageText)
        addTimeline({ type: 'error', title: '响应失败', detail: messageText })
      }
    }
  }, [addTimeline, requestInterrupt, session, updateAssistant])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    if (session) void requestInterrupt(session.sessionId, activeRunIdRef.current ?? undefined)
  }, [requestInterrupt, session])
  const clear = useCallback(() => {
    const currentSession = session
    const currentRunId = activeRunIdRef.current ?? undefined
    turnRevisionRef.current += 1
    abortRef.current?.abort()
    if (currentSession) void requestInterrupt(currentSession.sessionId, currentRunId)
    activeRunIdRef.current = null
    setMessages([])
    setTimeline([])
    setError(null)
  }, [requestInterrupt, session])

  return { messages, timeline, isSending, error, sendMessage, stop, clear, formatTime }
}
