import type { TelemetryEvent, TraceGroup } from './types'

const eventLabels: Record<string, string> = {
  'agent.invoke': 'Agent 请求',
  'agent.stream': '流式响应',
  receive: '接收消息',
  retrieve: '知识检索',
  'rag.search': 'RAG 检索',
  tool: '工具调用',
  'mcp.call': 'MCP 工具',
  respond: '生成回复',
  provider: '数字人 Provider',
  'provider.event': 'Provider 事件',
  'span.start': '开始执行',
  trace: '请求链路',
}

const attributeLabels: Record<string, string> = {
  provider: 'Provider',
  hit_count: '命中片段',
  message_length: '消息长度',
  collection: '知识集合',
  tool: '工具',
  tool_name: '工具',
  backend: '遥测后端',
  documents: '文档数量',
}

const hiddenKeys = new Set(['trace_id', 'span_id', 'parent_span_id', 'session_id', 'user_id', 'api_key', 'secret_key', 'token'])

const FIRST_EVENT_NAMES = new Set(['agent.first_byte', 'stream.first_event', 'first_event'])
const FIRST_VISIBLE_NAMES = new Set(['agent.first_visible', 'stream.first_visible', 'first_visible'])
const AGENT_LATENCY_NAMES = new Set(['agent.invoke', 'agent.stream', 'agent.completed', 'agent.complete'])
const DIGITAL_HUMAN_LATENCY_NAMES = new Set(['provider', 'send_text', 'digital_human', 'avatar'])
const CANCELLATION_NAMES = new Set(['cancel', 'cancelled', 'cancellation', 'interrupt', 'interrupted', 'run.stop', 'run.interrupted'])

export function eventLabel(event: TelemetryEvent): string {
  const name = String(event.name ?? event.event_type ?? '运行事件')
  if (eventLabels[name]) return eventLabels[name]
  if (name.includes('rag')) return 'RAG 检索'
  if (name.includes('mcp') || name.includes('tool')) return 'MCP 工具'
  if (name.includes('provider') || name.includes('avatar')) return '数字人 Provider'
  return name.replace(/[._-]+/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase())
}

export function eventTypeLabel(value?: string): string {
  if (!value) return '运行事件'
  const labels: Record<string, string> = {
    'span.start': '开始阶段',
    trace: '请求链路',
    'langgraph.node': 'Agent 节点',
    'mcp.call': 'MCP 调用',
    'rag.retrieval': '知识检索',
    'provider.event': 'Provider 事件',
    event: '运行事件',
  }
  return labels[value] ?? eventLabel({ name: value, event_type: value })
}

export function safeErrorMessage(value?: string | null): string | undefined {
  if (!value) return undefined
  const sanitized = value
    .replace(/(api[_-]?key|secret[_-]?key|token|password)\s*[:=]\s*[^\s,;]+/gi, '$1：已隐藏')
    .replace(/\b[a-f0-9]{24,}\b/gi, '内部标识已隐藏')
  return sanitized.length > 180 ? `${sanitized.slice(0, 177)}…` : sanitized
}

export function eventStatus(event: TelemetryEvent): 'ok' | 'error' | 'unset' {
  if (event.status === 'error' || event.error_message) return 'error'
  if (event.status === 'ok') return 'ok'
  return 'unset'
}

export function statusLabel(status: 'ok' | 'error' | 'unset'): string {
  return status === 'ok' ? '正常' : status === 'error' ? '异常' : '处理中'
}

export function formatDuration(value?: number | null): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return '—'
  if (value < 1000) return `${Math.round(value)} ms`
  return `${(value / 1000).toFixed(2)} s`
}

export function safeAttributes(event: TelemetryEvent): string[] {
  return Object.entries(event.attributes ?? {})
    .filter(([key, value]) => !hiddenKeys.has(key.toLowerCase()) && value !== undefined && value !== null)
    .filter(([key]) => Boolean(attributeLabels[key]))
    .slice(0, 5)
    .map(([key, value]) => `${attributeLabels[key]}：${safeValue(value)}`)
}

export function groupTraces(events: TelemetryEvent[]): TraceGroup[] {
  const buckets = new Map<string, TelemetryEvent[]>()
  for (const event of events) {
    const key = event.trace_id || event.event_id || `${event.name}-${event.timestamp}`
    const bucket = buckets.get(key) ?? []
    bucket.push(event)
    buckets.set(key, bucket)
  }
  return [...buckets.entries()]
    .map(([id, bucket]) => {
      const ordered = [...bucket].sort(compareEventOrder)
      const duration = wallDuration(ordered)
      // span.start is intentionally unset while a trace is running. Once an
      // end event is present, it must not downgrade the completed group to
      // the user-facing "处理中" state.
      const status: TraceGroup['status'] = ordered.some((event) => eventStatus(event) === 'error')
        ? 'error'
        : ordered.some((event) => eventStatus(event) === 'ok')
          ? 'ok'
          : 'unset'
      return {
        id,
        label: '',
        startedAt: ordered[0]?.timestamp,
        durationMs: duration,
        status,
        events: ordered,
        firstEventLatencyMs: latencyFor(ordered, FIRST_EVENT_NAMES, ['first_event_latency_ms', 'first_byte_latency_ms', 'latency_ms']),
        firstVisibleLatencyMs: latencyFor(ordered, FIRST_VISIBLE_NAMES, ['first_visible_latency_ms', 'visible_latency_ms', 'latency_ms']),
        cancellationLatencyMs: latencyFor(ordered, CANCELLATION_NAMES, ['cancellation_latency_ms', 'cancel_latency_ms', 'cancelLatencyMs', 'latency_ms']),
        agentLatencyMs: latencyFor(ordered, AGENT_LATENCY_NAMES, ['agent_latency_ms', 'agentLatencyMs']),
        digitalHumanLatencyMs: latencyFor(ordered, DIGITAL_HUMAN_LATENCY_NAMES, ['digital_human_latency_ms', 'digitalHumanLatencyMs', 'avatar_latency_ms']),
      }
    })
    .sort((a, b) => compareEventOrder(b.events[0], a.events[0]))
    .map((group, index) => ({ ...group, label: `运行记录 ${String(index + 1).padStart(2, '0')}` }))
}

function compareEventOrder(a?: TelemetryEvent, b?: TelemetryEvent): number {
  const left = sequenceOf(a)
  const right = sequenceOf(b)
  if (left !== undefined || right !== undefined) {
    if (left === undefined) return 1
    if (right === undefined) return -1
    if (left !== right) return left - right
  }
  return timestampOf(a) - timestampOf(b)
}

function sequenceOf(event?: TelemetryEvent): number | undefined {
  const value = event?.sequence
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : undefined
}

function latencyFor(events: TelemetryEvent[], names: Set<string>, attributes: string[]): number | undefined {
  const values: number[] = []
  for (const event of events) {
    const normalizedName = String(event.name ?? '').toLowerCase()
    if (!names.has(normalizedName) && ![...names].some((part) => normalizedName.includes(part))) continue
    const value = attributeNumber(event.attributes, attributes)
    if (value !== undefined) values.push(value)
    else {
      const duration = event.duration_ms
      if (duration !== undefined && duration !== null && event.event_type !== 'span.start') values.push(duration)
    }
  }
  return values.length ? Math.min(...values) : undefined
}

function attributeNumber(attributes: Record<string, unknown> | undefined, names: string[]): number | undefined {
  for (const name of names) {
    const value = attributes?.[name]
    if (value === undefined || value === null || typeof value === 'boolean') continue
    if (typeof value === 'string' && value.trim() === '') continue
    const parsed = typeof value === 'number' ? value : Number(value)
    if (Number.isFinite(parsed) && parsed >= 0) return parsed
  }
  return undefined
}

function timestampOf(event?: TelemetryEvent): number {
  const value = event?.timestamp ? Date.parse(event.timestamp) : 0
  return Number.isFinite(value) ? value : 0
}

function wallDuration(events: TelemetryEvent[]): number {
  if (events.length < 2) return Math.max(0, events[0]?.duration_ms ?? 0)
  const started = timestampOf(events[0])
  const ended = timestampOf(events[events.length - 1])
  if (started > 0 && ended >= started) return ended - started
  return events.reduce((sum, event) => sum + (event.duration_ms ?? 0), 0)
}

function safeValue(value: unknown): string {
  if (typeof value === 'string') return value.length > 80 ? `${value.slice(0, 77)}…` : value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return '[结构化数据]'
}
