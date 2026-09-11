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

export type TracePhaseKey = 'capture' | 'asr' | 'agent' | 'speech' | 'playback'

export interface TracePhase {
  key: TracePhaseKey
  label: string
  /** Offset from the trace's first event; drives the waterfall position. */
  startOffsetMs: number
  durationMs?: number
  status: 'ok' | 'error' | 'unset'
  eventCount: number
  firstEventName?: string
  lastEventName?: string
  /** False when nothing was reported for this phase, i.e. a real blind spot. */
  observed: boolean
  errorMessage?: string
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
  phases: TracePhase[]
  origin: 'browser' | 'server'
  coverage: TracePhaseKey[]
}

export type AuditFilter = 'all' | 'errors' | 'rag' | 'provider'
