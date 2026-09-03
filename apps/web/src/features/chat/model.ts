import { useCallback, useEffect, useRef, useState } from 'react'
import type { AvatarPerformanceCue, AvatarSession, ChatStreamEvent } from '../../shared/api/types'
import { formatTime, sanitizeDisplayText } from '../../shared/lib/format'
import * as chatApi from './api'
import { StreamEventGate } from './streamOrdering'
import { presentStreamEvent, type StreamEventState } from './streamEventPresenter'
import { recoverableStreamMessage, streamFailureAction } from './streamRecovery'
import { normalizeToolCall, toolDetail } from './streamPresentation'
import { AssistantDeltaBatcher } from './deltaBatch'
import { createConversation, readConversations, writeConversations } from './conversationStore'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  createdAt: string
  pending?: boolean
  /** 流式首响阶段的临时提示，不会混入最终回复。 */
  statusText?: string
  traceId?: string
  presentation?: AvatarPerformanceCue
}

export interface TimelineItem {
  id: string
  type: 'start' | 'filler' | 'intent' | 'disclosure' | 'security' | 'rag' | 'tool' | 'provider' | 'performance' | 'delta' | 'done' | 'interrupted' | 'error' | 'info'
  title: string
  detail?: string
  createdAt: string
  seq?: number
  approvalId?: string
  approvalStatus?: 'pending' | 'approved' | 'rejected' | 'failed'
}

export interface ChatConversation {
  id: string
  title: string
  createdAt: string
  updatedAt: string
  messages: ChatMessage[]
}

const id = (prefix: string) => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
const MAX_TIMELINE_ITEMS = 400
const MAX_CONTEXT_MESSAGES = 12
const HISTORY_WRITE_DELAY_MS = 240

export function useChat(session: AvatarSession | null, accountId?: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [conversations, setConversations] = useState<ChatConversation[]>([])
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [timeline, setTimeline] = useState<TimelineItem[]>([])
  const [isSending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const turnRevisionRef = useRef(0)
  const activeSessionIdRef = useRef<string | null>(null)
  const activeRunIdRef = useRef<string | null>(null)
  const interruptRef = useRef<{ sessionId: string; runId?: string; promise: Promise<void> } | null>(null)
  const messagesRef = useRef<ChatMessage[]>([])
  const activeConversationIdRef = useRef<string | null>(null)
  const historyReadyRef = useRef(false)
  const historyWriteTimerRef = useRef<number | null>(null)

  useEffect(() => { messagesRef.current = messages }, [messages])
  useEffect(() => { activeConversationIdRef.current = activeConversationId }, [activeConversationId])

  useEffect(() => {
    if (historyWriteTimerRef.current !== null) window.clearTimeout(historyWriteTimerRef.current)
    historyReadyRef.current = false
    if (!accountId) {
      setConversations([])
      setActiveConversationId(null)
      setMessages([])
      return
    }
    const stored = readConversations(accountId)
    const initial = stored[0] ?? createConversation()
    const next = stored.length ? stored : [initial]
    setConversations(next)
    setActiveConversationId(initial.id)
    setMessages(initial.messages)
    historyReadyRef.current = true
    if (!stored.length) writeConversations(accountId, next)
    return () => {
      if (historyWriteTimerRef.current !== null) window.clearTimeout(historyWriteTimerRef.current)
    }
  }, [accountId])

  useEffect(() => {
    if (!historyReadyRef.current || !accountId || !activeConversationId) return
    if (historyWriteTimerRef.current !== null) window.clearTimeout(historyWriteTimerRef.current)
    const snapshot = messages.map((message) => ({ ...message, pending: false, statusText: undefined }))
    historyWriteTimerRef.current = window.setTimeout(() => {
      setConversations((current) => {
        const existing = current.find((item) => item.id === activeConversationId) ?? createConversation()
        const firstUser = snapshot.find((message) => message.role === 'user' && message.content.trim())
        const updated: ChatConversation = {
          ...existing,
          id: activeConversationId,
          title: firstUser?.content.trim().slice(0, 32) || existing.title,
          updatedAt: new Date().toISOString(),
          messages: snapshot,
        }
        const next = [updated, ...current.filter((item) => item.id !== activeConversationId)]
        writeConversations(accountId, next)
        return next
      })
      historyWriteTimerRef.current = null
    }, HISTORY_WRITE_DELAY_MS)
    return () => {
      if (historyWriteTimerRef.current !== null) window.clearTimeout(historyWriteTimerRef.current)
    }
  }, [accountId, activeConversationId, messages])

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
    setTimeline((current) => {
      const next = [...current, { ...item, id: id('event'), createdAt: new Date().toISOString() }]
      return next.length > MAX_TIMELINE_ITEMS ? next.slice(-MAX_TIMELINE_ITEMS) : next
    })
  }, [])

  const resolveApproval = useCallback(async (approvalId: string, approved: boolean) => {
    if (!session) return
    setTimeline((current) => current.map((item) => item.approvalId === approvalId
      ? { ...item, approvalStatus: approved ? 'approved' : 'rejected', detail: approved ? '已批准，Agent 正在继续执行' : '已拒绝，Agent 将跳过该工具' }
      : item))
    try {
      const accepted = await chatApi.resolveApproval(session.sessionId, approvalId, approved)
      if (!accepted) {
        setTimeline((current) => current.map((item) => item.approvalId === approvalId
          ? { ...item, approvalStatus: 'failed', detail: '确认已过期或不属于当前会话' }
          : item))
      }
    } catch (cause) {
      const message = sanitizeDisplayText(cause instanceof Error ? cause.message : '确认请求失败')
      setTimeline((current) => current.map((item) => item.approvalId === approvalId
        ? { ...item, approvalStatus: 'failed', detail: message }
        : item))
    }
  }, [session])

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
        ? { ...message, pending: false, statusText: undefined, content: message.content || '本次响应已打断。' }
        : message))
      addTimeline({ type: 'interrupted', title: '已切换新指令', detail: '上一轮响应已停止，正在处理最新输入' })
    }
    previousController?.abort()
    const pendingInterrupt = previousController
      ? requestInterrupt(sessionId, previousRunId)
      : !previousRunId
        && interruptRef.current?.sessionId === sessionId
        && interruptRef.current.runId === undefined
        ? interruptRef.current.promise
        : null
    activeRunIdRef.current = null
    // 已拿到 runId 时，中断请求带有精确作用域，可以和新一轮请求并行，
    // 避免把一次网关往返时间叠加到用户的改口延迟上。尚未拿到 runId
    // 时仍需等待无作用域中断完成，防止它误伤即将创建的新 run。
    if (pendingInterrupt && !previousRunId) {
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
    const eventState: StreamEventState = {
      accumulated: '',
      sawTerminal: false,
      sawInterrupted: false,
      executionStarted: false,
      deltaCount: 0,
    }
    const eventGate = new StreamEventGate()
    const deltaBatcher = new AssistantDeltaBatcher((messageId, patch) => {
      if (isCurrentTurn()) updateAssistant(messageId, patch)
    })

    const onEvent = (event: ChatStreamEvent) => {
      if (!isCurrentTurn() || controller.signal.aborted) return
      const accepted = eventGate.accept(event)
      if (!accepted) return
      const eventRunId = typeof accepted.runId === 'string' ? accepted.runId : undefined
      if (eventRunId) activeRunIdRef.current = eventRunId
      presentStreamEvent(accepted, eventState, {
        assistantId,
        addTimeline,
        updateAssistant,
        updateAssistantBatched: (messageId, patch) => deltaBatcher.enqueue(messageId, patch),
        setError: (messageText) => setError(messageText),
      })
      const eventKind = String(accepted.type ?? '').toLowerCase()
      if ((eventKind === 'done' && !eventState.preExecutionError) || eventKind === 'interrupted') {
        // The terminal frame releases the session ownership immediately;
        // this prevents a later clear/unmount from interrupting a finished run.
        activeRunIdRef.current = null
        if (abortRef.current === controller) {
          abortRef.current = null
          setSending(false)
        }
      }
    }

    const history = messagesRef.current
      .filter((item) => !item.pending && (item.role === 'user' || item.role === 'assistant') && item.content.trim())
      .slice(-MAX_CONTEXT_MESSAGES)
      .map((item) => ({ role: item.role as 'user' | 'assistant', content: item.content.trim().slice(0, 2000) }))

    try {
      await chatApi.streamChat({ sessionId, message, history }, onEvent, controller.signal)
      if (!isCurrentTurn()) return
      const action = streamFailureAction({ executionStarted: eventState.executionStarted, preExecutionError: eventState.preExecutionError, terminal: eventState.sawTerminal || eventState.sawInterrupted, aborted: controller.signal.aborted })
      if (action === 'fallback') {
        deltaBatcher.flush()
        await completeWithSyncFallback()
      } else if (action === 'stopped') {
        deltaBatcher.flush()
        updateAssistant(assistantId, { content: eventState.accumulated || '本次响应已停止。', pending: false, statusText: undefined, traceId: eventState.traceId })
        addTimeline({ type: 'info', title: '已停止生成' })
      } else if (!eventState.sawTerminal && !eventState.sawInterrupted) {
        deltaBatcher.flush()
        updateAssistant(assistantId, { content: eventState.accumulated || '服务端已结束响应。', pending: false, statusText: undefined, traceId: eventState.traceId })
        addTimeline({ type: 'done', title: '响应完成', detail: '运行链路已完成' })
      }
    } catch (cause) {
      if (!isCurrentTurn()) return
      const action = streamFailureAction({ executionStarted: eventState.executionStarted, preExecutionError: eventState.preExecutionError, terminal: eventState.sawTerminal || eventState.sawInterrupted, aborted: controller.signal.aborted })
      if (action === 'stopped') {
        deltaBatcher.flush()
        updateAssistant(assistantId, { content: eventState.accumulated || '本次响应已停止。', pending: false, statusText: undefined, traceId: eventState.traceId })
        addTimeline({ type: 'info', title: '已停止生成' })
      } else if (action === 'fallback') {
        deltaBatcher.flush()
        await completeWithSyncFallback(cause)
      } else if (action === 'recoverable') {
        deltaBatcher.flush()
        const recoverable = recoverableStreamMessage(Boolean(eventState.accumulated))
        updateAssistant(assistantId, { content: eventState.accumulated || recoverable, pending: false, statusText: undefined, traceId: eventState.traceId })
        setError(recoverable)
        addTimeline({ type: 'error', title: '流式响应中断', detail: recoverable })
      } else {
        deltaBatcher.flush()
        updateAssistant(assistantId, { content: eventState.accumulated || '服务端已结束响应。', pending: false, statusText: undefined, traceId: eventState.traceId })
      }
    } finally {
      if (isCurrentTurn()) {
        deltaBatcher.flush()
        abortRef.current = null
        // A completed turn no longer owns the session. Leaving this id in the
        // ref would make clear/unmount issue a late session-level interrupt.
        activeRunIdRef.current = null
        setSending(false)
      } else {
        deltaBatcher.cancel()
      }
    }

    async function completeWithSyncFallback(streamCause?: unknown) {
      if (!isCurrentTurn()) return
      try {
        addTimeline({ type: 'info', title: '流式连接未开始执行，切换同步响应' })
        const response = await chatApi.sendChat({ sessionId, message, history }, controller.signal)
        if (!isCurrentTurn()) return
        if (response.runId) activeRunIdRef.current = response.runId
        updateAssistant(assistantId, { content: response.reply, pending: false, statusText: undefined, traceId: response.traceId, presentation: response.agentResponse?.presentation ?? response.agentResponse?.performance })
        for (const tool of response.toolCalls ?? []) {
          const normalizedTool = normalizeToolCall(tool)
          if (!normalizedTool) continue
          addTimeline({ type: 'tool', title: normalizedTool.name ? `调用工具 · ${sanitizeDisplayText(normalizedTool.name, 64)}` : '执行 MCP 工具', detail: toolDetail(normalizedTool) })
        }
        addTimeline({ type: 'done', title: '同步响应完成', detail: '运行链路已完成' })
      } catch (fallbackCause) {
        if (!isCurrentTurn()) return
        deltaBatcher.flush()
        const messageText = sanitizeDisplayText(fallbackCause instanceof Error ? fallbackCause.message : (streamCause instanceof Error ? streamCause.message : '请求失败'))
        updateAssistant(assistantId, { content: '暂时无法获得 Agent 响应。', pending: false, statusText: undefined })
        setError(messageText)
        addTimeline({ type: 'error', title: '响应失败', detail: messageText })
      }
    }
  }, [addTimeline, requestInterrupt, session, updateAssistant])

  const stop = useCallback(() => {
    const controller = abortRef.current
    const runId = activeRunIdRef.current ?? undefined
    if (!controller && !runId) return
    controller?.abort()
    abortRef.current = null
    activeRunIdRef.current = null
    setSending(false)
    if (session) void requestInterrupt(session.sessionId, runId)
  }, [requestInterrupt, session])
  const clear = useCallback(() => {
    const currentSession = session
    const currentRunId = activeRunIdRef.current ?? undefined
    const hasActiveRun = Boolean(abortRef.current || currentRunId)
    turnRevisionRef.current += 1
    abortRef.current?.abort()
    if (currentSession && hasActiveRun) void requestInterrupt(currentSession.sessionId, currentRunId)
    abortRef.current = null
    activeRunIdRef.current = null
    setSending(false)
    setMessages([])
    setTimeline([])
    setError(null)
  }, [requestInterrupt, session])

  const newConversation = useCallback(() => {
    stop()
    const next = createConversation()
    activeConversationIdRef.current = next.id
    setActiveConversationId(next.id)
    setMessages([])
    setTimeline([])
    setError(null)
    setConversations((current) => {
      const records = [next, ...current]
      if (accountId) writeConversations(accountId, records)
      return records
    })
  }, [accountId, stop])

  const selectConversation = useCallback((conversationId: string) => {
    const target = conversations.find((item) => item.id === conversationId)
    if (!target || target.id === activeConversationIdRef.current) return
    stop()
    activeConversationIdRef.current = target.id
    setActiveConversationId(target.id)
    setMessages(target.messages.map((message) => ({ ...message, pending: false, statusText: undefined })))
    setTimeline([])
    setError(null)
  }, [conversations, stop])

  const deleteConversation = useCallback((conversationId: string) => {
    const remaining = conversations.filter((item) => item.id !== conversationId)
    let nextRecords = remaining
    if (!remaining.length) nextRecords = [createConversation()]
    if (activeConversationIdRef.current === conversationId) {
      stop()
      const next = nextRecords[0]
      activeConversationIdRef.current = next.id
      setActiveConversationId(next.id)
      setMessages(next.messages)
      setTimeline([])
    }
    setConversations(nextRecords)
    if (accountId) writeConversations(accountId, nextRecords)
  }, [accountId, conversations, stop])

  return { messages, conversations, activeConversationId, timeline, isSending, error, sendMessage, resolveApproval, stop, clear, newConversation, selectConversation, deleteConversation, formatTime }
}
