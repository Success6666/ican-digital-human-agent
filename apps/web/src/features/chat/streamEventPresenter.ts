import type { ChatStreamEvent, ToolCall } from '../../shared/api/types'
import { sanitizeDisplayText } from '../../shared/lib/format'
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
import type { ChatMessage, TimelineItem } from './model'
import { markBusinessEvent } from './streamRecovery'

export interface StreamEventState {
  accumulated: string
  traceId?: string
  sawTerminal: boolean
  sawInterrupted: boolean
  executionStarted: boolean
  preExecutionError?: boolean
  deltaCount: number
}

export interface StreamEventPresenterContext {
  assistantId: string
  addTimeline: (item: Omit<TimelineItem, 'id' | 'createdAt'>) => void
  updateAssistant: (messageId: string, patch: Partial<ChatMessage>) => void
  setError: (message: string) => void
}

/** 将已通过 run/seq/eventId 校验的事件转换成人类可读状态。 */
export function presentStreamEvent(
  event: ChatStreamEvent,
  state: StreamEventState,
  context: StreamEventPresenterContext,
): void {
  const kind = String(event.type ?? 'message').toLowerCase()
  state.traceId = typeof event.traceId === 'string' ? event.traceId : state.traceId
  if (markBusinessEvent(kind)) state.executionStarted = true

  if (kind === 'start') {
    context.addTimeline({ type: 'start', title: 'Agent 开始处理', detail: performanceText(event) ?? '运行链路已启动', seq: event.seq })
    return
  }
  if (kind === 'filler') {
    const filler = eventText(event)
    const statusText = filler ? sanitizeDisplayText(filler, 180) : performanceText(event)
    if (statusText && !state.accumulated) context.updateAssistant(context.assistantId, { statusText })
    context.addTimeline({ type: 'filler', title: '数字人正在思考', detail: statusText, seq: event.seq })
    return
  }
  if (kind === 'intent') {
    context.addTimeline({ type: 'intent', title: '已识别用户意图', detail: `${intentText(event.intent)} · 置信度 ${confidenceText(event.confidence)}`, seq: event.seq })
    return
  }
  if (kind === 'tool_disclosure') {
    const names = disclosureNames(event.tools)
    context.addTimeline({ type: 'disclosure', title: '已规划工具调用', detail: names ? `计划使用：${names}` : '按需选择 MCP 工具', seq: event.seq })
    return
  }
  if (kind === 'security') {
    context.addTimeline({ type: 'security', title: event.blocked === true ? '已拦截不安全请求' : '安全检查通过', detail: event.blocked === true ? '已跳过知识检索与工具调用' : '输入未命中安全策略', seq: event.seq })
    return
  }
  if (kind === 'tool') {
    appendToolTimeline(event, context)
    return
  }
  if (kind === 'rag') {
    const hitCount = typeof event.hitCount === 'number' ? event.hitCount : 0
    const degraded = event.degraded === true
    context.addTimeline({
      type: 'rag',
      title: degraded ? 'RAG 检索降级' : 'RAG 检索完成',
      detail: degraded ? '文档检索暂不可用，继续执行主链路' : `命中 ${hitCount} 个片段`,
      seq: event.seq,
    })
    return
  }
  if (kind === 'provider') {
    context.addTimeline({ type: 'provider', title: 'Provider 返回结果', detail: performanceText(event) ?? providerStatusText(event.status), seq: event.seq })
    return
  }
  if (kind === 'delta' || kind === 'message') {
    const chunk = eventText(event)
    if (!chunk) return
    state.accumulated += chunk
    context.updateAssistant(context.assistantId, { content: state.accumulated, statusText: undefined, traceId: state.traceId })
    if (state.deltaCount === 0 || state.deltaCount % 16 === 0) {
      context.addTimeline({ type: 'delta', title: '正在生成响应', detail: `已接收 ${state.accumulated.length} 字符`, seq: event.seq })
    }
    state.deltaCount += 1
    return
  }
  if (kind === 'done') {
    state.sawTerminal = true
    const finalReply = eventText(event) || state.accumulated
    state.accumulated = finalReply
    context.updateAssistant(context.assistantId, { content: finalReply, pending: false, statusText: undefined, traceId: state.traceId })
    context.addTimeline({ type: 'done', title: '响应完成', detail: event.interrupted === true ? '本次响应已打断' : performanceText(event) ?? '运行链路已完成', seq: event.seq })
    return
  }
  if (kind === 'interrupted') {
    state.sawInterrupted = true
    const interruptedText = eventText(event) || '本次响应已打断。'
    state.accumulated = state.accumulated || interruptedText
    context.updateAssistant(context.assistantId, { content: state.accumulated, pending: false, statusText: undefined, traceId: state.traceId })
    context.addTimeline({ type: 'interrupted', title: '已停止生成', detail: performanceText(event) ?? sanitizeDisplayText(interruptedText), seq: event.seq })
    return
  }
  if (kind === 'error') {
    // 流尚未产生任何业务事件时，error 多半来自网关建连或上游握手。
    // 交给外层的同步 fallback，避免把一次可恢复的建连失败直接呈现为终态。
    if (!state.executionStarted) {
      state.preExecutionError = true
      return
    }
    state.sawTerminal = true
    const messageText = sanitizeDisplayText(String(event.message || eventText(event) || 'Agent 返回错误'))
    context.updateAssistant(context.assistantId, { content: state.accumulated || '暂时无法获得 Agent 响应。', pending: false, statusText: undefined, traceId: state.traceId })
    context.setError(messageText)
    context.addTimeline({ type: 'error', title: '响应失败', detail: messageText, seq: event.seq })
  }
}

function appendToolTimeline(event: ChatStreamEvent, context: StreamEventPresenterContext): void {
  const tools = eventTools(event)
  const tool = eventTool(event)
  if (tools.length) {
    for (const call of tools) appendToolCall(call, event.seq, context)
    return
  }
  context.addTimeline({
    type: 'tool',
    title: tool?.name ? `调用工具 · ${sanitizeDisplayText(tool.name, 64)}` : '执行 MCP 工具',
    detail: tool ? toolDetail(tool) : '工具事件已记录',
    seq: event.seq,
  })
}

function appendToolCall(tool: ToolCall, seq: number | undefined, context: StreamEventPresenterContext): void {
  context.addTimeline({
    type: 'tool',
    title: tool.name ? `调用工具 · ${sanitizeDisplayText(tool.name, 64)}` : '执行 MCP 工具',
    detail: toolDetail(tool),
    seq,
  })
}
