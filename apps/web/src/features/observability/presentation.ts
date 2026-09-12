import type { TelemetryEvent, TraceGroup, TracePhase, TracePhaseKey } from './types'

const eventLabels: Record<string, string> = {
  'agent.invoke': 'Agent 请求',
  'agent.stream': '流式响应',
  'agent.first_byte': '首个字节',
  'agent.first_visible': '首段可见',
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
  // Browser-reported realtime markers.
  'capture.permission_request': '申请麦克风权限',
  'capture.permission_granted': '麦克风已授权',
  'capture.permission_denied': '麦克风被拒绝',
  'capture.recorder_started': '开始录音',
  'capture.recorder_stopped': '结束录音',
  'capture.recorder_failed': '录音启动失败',
  'capture.track_ended': '音轨结束',
  'capture.first_frame': '首帧音频',
  'realtime.client_connected': '实时通道已连接',
  'realtime.client_disconnected': '实时通道已断开',
  'realtime.client_send_failed': '实时发送失败',
  'realtime.phase': '阶段变化',
  'speech.assembled': '装配播报文本',
  'speech.skipped': '跳过播报',
  'speech.dispatch_failed': '播报派发失败',
  'speech.dropped': '播报片段被丢弃',
  'speech.ack_timeout': '播报未获确认',
  'speech.interrupted': '播报被打断',
  'speak.dispatched': '提交播报',
  'speak.started': '开始发声',
  'speak.ended': '发声结束',
  'speak.failed': '发声失败',
  'speak.timeout': '发声超时',
  'ttsa.warning': 'TTSA 会话告警',
  'ttsa.recovered': 'TTSA 已恢复',
  'avatar.connect_started': '开始连接数字人',
  'avatar.connect_failed': '数字人连接失败',
  'avatar.ready_achieved': '数字人就绪',
  'avatar.ready_blocked': '数字人卡在未就绪',
  'avatar.phase_changed': '数字人阶段变化',
  'avatar.audio_unlocked': '音频已解锁',
  'avatar.audio_blocked': '音频被浏览器拦截',
  'realtime.run_started': '本轮开始',
  'realtime.first_transcript': '首个转写',
  'asr.capture_started': '开始采集音频',
  'asr.audio_buffered': '音频累积',
  'asr.buffer_truncated': '音频缓冲溢出（已丢弃开头）',
  'asr.finished': '识别完成',
  'asr.failed': '识别失败',
  'realtime.tts_dropped': '服务端语音合成被丢弃',
  'realtime.first_delta': '首个增量',
  'realtime.audio_queue': '音频入队',
  'realtime.interrupt_ack': '打断确认',
  'realtime.run_terminal': '本轮结束',
  'realtime.first_audio_output': '首个音频输出',
  'realtime.ready': '实时通道就绪',
  'realtime.closed': '实时通道关闭',
  'security_gate': '安全校验',
  send_text: '发送文本',
  system_status: '系统状态',
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
  reason: '原因',
  phase: '阶段',
  code: '错误码',
  textLength: '文本长度',
  text_length: '文本长度',
  deltaLength: '增量长度',
  totalLength: '总长度',
  pendingLength: '待播长度',
  trackedCount: '音频上下文数',
  isStart: '首段',
  isEnd: '末段',
  flush: '已收尾',
  hasEmotion: '含情绪',
  hasPresentation: '含动作',
  sampleRate: '采样率',
  channels: '声道',
  frameMs: '帧长',
  capabilities: '能力协商',
  clientSpeakId: '播报标识',
  source: '来源',
  origin: '来源',
  revision: '轮次',
  run_id: '运行标识',
  utterance_id: '话轮标识',
  frames: '音频帧数',
  received_bytes: '接收字节',
  buffered_bytes: '缓冲字节',
  dropped_frames: '丢弃帧数',
  status: '状态',
}

const hiddenKeys = new Set([
  'trace_id',
  'span_id',
  'parent_span_id',
  'session_id',
  'connection_id',
  'user_id',
  'owner_id',
  'api_key',
  'secret_key',
  'token',
])

const FIRST_EVENT_NAMES = new Set(['agent.first_byte', 'stream.first_event', 'first_event'])
const FIRST_VISIBLE_NAMES = new Set(['agent.first_visible', 'stream.first_visible', 'first_visible'])
const AGENT_LATENCY_NAMES = new Set(['agent.invoke', 'agent.stream', 'agent.completed', 'agent.complete'])
const DIGITAL_HUMAN_LATENCY_NAMES = new Set(['provider', 'send_text', 'digital_human', 'avatar'])
const CANCELLATION_NAMES = new Set(['cancel', 'cancelled', 'cancellation', 'interrupt', 'interrupted', 'run.stop', 'run.interrupted'])

export const TRACE_PHASE_KEYS: TracePhaseKey[] = ['capture', 'asr', 'agent', 'speech', 'playback']

export const TRACE_PHASE_LABELS: Record<TracePhaseKey, string> = {
  capture: '采集',
  asr: '识别',
  agent: '理解',
  speech: '装配',
  playback: '播报',
}

export const TRACE_PHASE_HINTS: Record<TracePhaseKey, string> = {
  capture: '浏览器麦克风授权与录音帧',
  asr: '语音识别（服务端）',
  agent: 'Agent 图与首 token',
  speech: '增量文本装配为播报段',
  playback: '魔珐 SDK 发声与 TTSA 会话',
}

/**
 * Phase membership. Matching by prefix means a new marker added inside an
 * existing phase is picked up without touching this table, but the order of
 * the entries still decides which phase wins for an ambiguous name.
 */
const PHASE_PREFIXES: Array<[TracePhaseKey, string[]]> = [
  ['capture', ['capture.']],
  ['asr', ['asr.', 'realtime.first_transcript']],
  ['agent', ['agent.', 'security_gate', 'receive', 'realtime.run_started']],
  ['speech', ['speech.', 'realtime.first_delta', 'realtime.audio_queue', 'send_text']],
  ['playback', ['speak.', 'ttsa.', 'realtime.first_audio_output', 'realtime.interrupt_ack']],
]

function phaseForName(name: string): TracePhaseKey | undefined {
  const normalized = name.toLowerCase()
  for (const [key, prefixes] of PHASE_PREFIXES) {
    if (prefixes.some((prefix) => normalized === prefix || normalized.startsWith(prefix))) return key
  }
  return undefined
}

/**
 * Bucket a trace's events into the five end-to-end phases.
 *
 * Unobserved phases are still returned so the console renders a visible gap
 * rather than hiding a stage the browser never reported — that gap is the
 * whole point of tracing "the digital human went silent".
 */
export function groupPhases(events: TelemetryEvent[]): TracePhase[] {
  if (events.length === 0) return []
  const start = timestampOf(events[0])
  const buckets = new Map<TracePhaseKey, TelemetryEvent[]>(TRACE_PHASE_KEYS.map((key) => [key, []]))
  for (const event of events) {
    const name = String(event.name ?? event.event_type ?? '')
    const key = phaseForName(name)
    if (key) buckets.get(key)?.push(event)
  }
  return TRACE_PHASE_KEYS.map((key) => {
    const items = buckets.get(key) ?? []
    if (items.length === 0) {
      return {
        key,
        label: TRACE_PHASE_LABELS[key],
        startOffsetMs: 0,
        status: 'unset' as const,
        eventCount: 0,
        observed: false,
      }
    }
    const first = items[0]
    const last = items[items.length - 1]
    const status: TracePhase['status'] = items.some((event) => eventStatus(event) === 'error')
      ? 'error'
      : items.some((event) => eventStatus(event) === 'ok')
        ? 'ok'
        : 'unset'
    const failure = items.find((event) => eventStatus(event) === 'error')
    return {
      key,
      label: TRACE_PHASE_LABELS[key],
      startOffsetMs: Math.max(0, timestampOf(first) - start),
      // A single-marker phase has no measurable span; leaving it undefined
      // stops the waterfall from drawing a fake instantaneous bar.
      durationMs: items.length > 1 ? Math.max(0, timestampOf(last) - timestampOf(first)) : undefined,
      status,
      eventCount: items.length,
      firstEventName: String(first.name ?? first.event_type ?? ''),
      lastEventName: String(last.name ?? last.event_type ?? ''),
      observed: true,
      errorMessage: failure ? safeErrorMessage(failure.error_message) : undefined,
    }
  })
}

export function traceOrigin(events: TelemetryEvent[]): 'browser' | 'server' {
  return events.some((event) => event.attributes?.source === 'browser') ? 'browser' : 'server'
}


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
      const phases = groupPhases(ordered)
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
        phases,
        origin: traceOrigin(ordered),
        coverage: phases.filter((phase) => phase.observed).map((phase) => phase.key),
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
