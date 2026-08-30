export interface TelemetryEvent {
  event_id?: string
  sequence?: number
  event_type?: string
  name?: string
  trace_id?: string
  span_id?: string | null
  parent_span_id?: string | null
  timestamp?: string
  duration_ms?: number | null
  status?: 'ok' | 'error' | 'unset' | string
  attributes?: Record<string, unknown>
  error_type?: string | null
  error_message?: string | null
}

export interface TraceGroup {
  id: string
  label: string
  startedAt?: string
  durationMs: number
  status: 'ok' | 'error' | 'unset'
  events: TelemetryEvent[]
  firstEventLatencyMs?: number
  firstVisibleLatencyMs?: number
  cancellationLatencyMs?: number
  agentLatencyMs?: number
  digitalHumanLatencyMs?: number
}

export type AuditFilter = 'all' | 'errors' | 'rag' | 'provider'
