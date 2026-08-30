import type { ChatStreamEvent, ToolCall } from '../../shared/api/types'
import { sanitizeDisplayText } from '../../shared/lib/format'

export function eventText(event: ChatStreamEvent): string {
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

export function intentText(value: unknown): string {
  const key = String(value ?? '').toLowerCase()
  return intentLabels[key] ?? (key ? sanitizeDisplayText(key, 48) : '待识别')
}

export function performanceText(event: ChatStreamEvent): string | undefined {
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

export function eventTool(event: ChatStreamEvent): ToolCall | undefined {
  return normalizeToolCall(event.toolCall) ?? normalizeToolCall(event.tool)
}

export function eventTools(event: ChatStreamEvent): ToolCall[] {
  if (!Array.isArray(event.toolCalls)) return []
  return event.toolCalls
    .map((item) => normalizeToolCall(item))
    .filter((item): item is ToolCall => item !== undefined)
}

export function toolDetail(tool: ToolCall): string | undefined {
  const normalized = normalizeToolCall(tool) ?? tool
  if (normalized.status === 'failed') return '工具执行失败'
  if (normalized.status === 'running') return '工具执行中'
  if (typeof normalized.durationMs === 'number' && Number.isFinite(normalized.durationMs)) return `工具已完成 · ${Math.round(normalized.durationMs)} ms`
  return '工具已返回结果'
}

/** 将后端蛇形字段和前端展示字段统一为稳定的可读模型。 */
export function normalizeToolCall(value: unknown): ToolCall | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const record = value as Record<string, unknown>
  const name = typeof record.name === 'string' ? record.name : ''
  const explicitStatus = typeof record.status === 'string' ? record.status : undefined
  const hasResult = Object.prototype.hasOwnProperty.call(record, 'output')
    || Object.prototype.hasOwnProperty.call(record, 'result')
  const status = explicitStatus
    ?? (record.error ? 'failed' : hasResult ? 'completed' : 'running')
  const durationMs = finiteNumber(record.durationMs ?? record.duration_ms)
  return {
    name,
    status,
    input: record.input ?? record.arguments,
    output: record.output ?? record.result,
    ...(durationMs === undefined ? {} : { durationMs }),
  }
}

export function confidenceText(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  const normalized = value > 1 ? value : value * 100
  return `${Math.max(0, Math.min(100, normalized)).toFixed(0)}%`
}

export function disclosureNames(value: unknown): string | undefined {
  if (!Array.isArray(value)) return undefined
  const names = value.map((item) => {
    if (!item || typeof item !== 'object') return ''
    const record = item as Record<string, unknown>
    return sanitizeDisplayText(String(record.label ?? record.name ?? ''), 48)
  }).filter(Boolean).slice(0, 3)
  return names.length ? names.join('、') : undefined
}

export function providerStatusText(value: unknown): string | undefined {
  const status = String(value ?? '').toLowerCase()
  if (status === 'ok' || status === 'success' || status === 'completed') return 'Provider 已完成'
  if (status === 'interrupted' || status === 'cancelled') return 'Provider 已停止'
  if (status === 'error' || status === 'failed') return 'Provider 返回异常'
  return status ? `Provider 状态：${sanitizeDisplayText(status, 32)}` : undefined
}

function finiteNumber(value: unknown): number | undefined {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : NaN
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined
}
