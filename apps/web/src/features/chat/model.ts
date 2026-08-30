import { useCallback, useEffect, useRef, useState } from 'react'
import type { AvatarSession, ChatStreamEvent } from '../../shared/api/types'
import { formatTime, sanitizeDisplayText } from '../../shared/lib/format'
import * as chatApi from './api'
import { StreamEventGate } from './streamOrdering'
import { presentStreamEvent, type StreamEventState } from './streamEventPresenter'
import { recoverableStreamMessage, streamFailureAction } from './streamRecovery'
import { normalizeToolCall, toolDetail } from './streamPresentation'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  createdAt: string
  pending?: boolean
  /** 流式首响阶段的临时提示，不会混入最终回复。 */
  statusText?: string
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
const MAX_TIMELINE_ITEMS = 400

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
    setTimeline((current) => {
      const next = [...current, { ...item, id: id('event'), createdAt: new Date().toISOString() }]
      return next.length > MAX_TIMELINE_ITEMS ? next.slice(-MAX_TIMELINE_ITEMS) : next
    })
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

    try {
      await chatApi.streamChat({ sessionId, message }, onEvent, controller.signal)
      if (!isCurrentTurn()) return
      const action = streamFailureAction({ executionStarted: eventState.executionStarted, preExecutionError: eventState.preExecutionError, terminal: eventState.sawTerminal || eventState.sawInterrupted, aborted: controller.signal.aborted })
      if (action === 'fallback') {
        await completeWithSyncFallback()
      } else if (action === 'stopped') {
        updateAssistant(assistantId, { content: eventState.accumulated || '本次响应已停止。', pending: false, statusText: undefined, traceId: eventState.traceId })
        addTimeline({ type: 'info', title: '已停止生成' })
      } else if (!eventState.sawTerminal && !eventState.sawInterrupted) {
        updateAssistant(assistantId, { content: eventState.accumulated || '服务端已结束响应。', pending: false, statusText: undefined, traceId: eventState.traceId })
        addTimeline({ type: 'done', title: '响应完成', detail: '运行链路已完成' })
      }
    } catch (cause) {
      if (!isCurrentTurn()) return
      const action = streamFailureAction({ executionStarted: eventState.executionStarted, preExecutionError: eventState.preExecutionError, terminal: eventState.sawTerminal || eventState.sawInterrupted, aborted: controller.signal.aborted })
      if (action === 'stopped') {
        updateAssistant(assistantId, { content: eventState.accumulated || '本次响应已停止。', pending: false, statusText: undefined, traceId: eventState.traceId })
        addTimeline({ type: 'info', title: '已停止生成' })
      } else if (action === 'fallback') {
        await completeWithSyncFallback(cause)
      } else if (action === 'recoverable') {
        const recoverable = recoverableStreamMessage(Boolean(eventState.accumulated))
        updateAssistant(assistantId, { content: eventState.accumulated || recoverable, pending: false, statusText: undefined, traceId: eventState.traceId })
        setError(recoverable)
        addTimeline({ type: 'error', title: '流式响应中断', detail: recoverable })
      } else {
        updateAssistant(assistantId, { content: eventState.accumulated || '服务端已结束响应。', pending: false, statusText: undefined, traceId: eventState.traceId })
      }
    } finally {
      if (isCurrentTurn()) {
        abortRef.current = null
        // A completed turn no longer owns the session. Leaving this id in the
        // ref would make clear/unmount issue a late session-level interrupt.
        activeRunIdRef.current = null
        setSending(false)
      }
    }

    async function completeWithSyncFallback(streamCause?: unknown) {
      if (!isCurrentTurn()) return
      try {
        addTimeline({ type: 'info', title: '流式连接未开始执行，切换同步响应' })
        const response = await chatApi.sendChat({ sessionId, message }, controller.signal)
        if (!isCurrentTurn()) return
        if (response.runId) activeRunIdRef.current = response.runId
        updateAssistant(assistantId, { content: response.reply, pending: false, statusText: undefined, traceId: response.traceId })
        for (const tool of response.toolCalls ?? []) {
          const normalizedTool = normalizeToolCall(tool)
          if (!normalizedTool) continue
          addTimeline({ type: 'tool', title: normalizedTool.name ? `调用工具 · ${sanitizeDisplayText(normalizedTool.name, 64)}` : '执行 MCP 工具', detail: toolDetail(normalizedTool) })
        }
        addTimeline({ type: 'done', title: '同步响应完成', detail: '运行链路已完成' })
      } catch (fallbackCause) {
        if (!isCurrentTurn()) return
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
    turnRevisionRef.current += 1
    abortRef.current?.abort()
    if (currentSession) void requestInterrupt(currentSession.sessionId, currentRunId)
    abortRef.current = null
    activeRunIdRef.current = null
    setSending(false)
    setMessages([])
    setTimeline([])
    setError(null)
  }, [requestInterrupt, session])

  return { messages, timeline, isSending, error, sendMessage, stop, clear, formatTime }
}
