import { api } from '../../shared/api/client'

/**
 * Browser-side trace reporting.
 *
 * The server can observe the transport but not microphone authorization, the
 * recorder lifecycle, the delta -> speech projection, or the vendor avatar
 * SDK's speak lifecycle. Those are the stages where "the digital human went
 * silent" actually happens, so the browser reports them into the same trace.
 *
 * Reporting is strictly fire-and-forget: a telemetry failure must never break
 * the voice loop, so every call is bounded, batched and swallowed.
 */

export type ClientEventStatus = 'ok' | 'error' | 'unset'

export interface ClientEventInput {
  name: string
  traceId: string
  runId?: string
  utteranceId?: string
  revision?: number
  durationMs?: number
  status?: ClientEventStatus
  attributes?: Record<string, unknown>
}

interface QueuedEvent {
  name: string
  trace_id: string
  run_id?: string
  utterance_id?: string
  revision?: number
  duration_ms?: number
  status: ClientEventStatus
  attributes: Record<string, unknown>
}

const MAX_QUEUE = 200
const MAX_BATCH = 32
const FLUSH_DELAY_MS = 400
const MAX_ATTRIBUTES = 16
const MAX_STRING = 256

const SECRET_KEY = /authorization|secret|token|password|cookie|api[-_]?key|credential|session/i

let queue: QueuedEvent[] = []
let timer: number | undefined
let flushing = false
let sessionId: string | undefined
let connectionId: string | undefined

export function setTelemetryContext(context: { sessionId?: string; connectionId?: string }): void {
  if (context.sessionId !== undefined) sessionId = context.sessionId || undefined
  if (context.connectionId !== undefined) connectionId = context.connectionId || undefined
}

export function reportClientEvent(event: ClientEventInput): void {
  if (typeof window === 'undefined') return
  const name = String(event.name || '').trim()
  const traceId = String(event.traceId || '').trim()
  if (!name || !traceId) return
  if (queue.length >= MAX_QUEUE) queue.shift()
  queue.push({
    name,
    trace_id: traceId.slice(0, 128),
    run_id: optionalId(event.runId),
    utterance_id: optionalId(event.utteranceId),
    revision: normalizeRevision(event.revision),
    duration_ms: normalizeDuration(event.durationMs),
    status: event.status ?? 'ok',
    attributes: sanitizeAttributes(event.attributes),
  })
  schedule()
}

/** Flush immediately; used on page hide and when a run reaches a terminal state. */
export function flushClientEvents(): void {
  if (typeof window === 'undefined') return
  if (timer !== undefined) {
    window.clearTimeout(timer)
    timer = undefined
  }
  void drain()
}

function schedule(): void {
  if (timer !== undefined || flushing) return
  timer = window.setTimeout(() => {
    timer = undefined
    void drain()
  }, FLUSH_DELAY_MS)
}

async function drain(): Promise<void> {
  if (flushing || queue.length === 0) return
  flushing = true
  try {
    while (queue.length > 0) {
      const batch = queue.splice(0, MAX_BATCH)
      try {
        await api.post('/telemetry/events', {
          events: batch,
          session_id: sessionId,
          connection_id: connectionId,
        })
      } catch {
        // Telemetry is diagnostic only. Dropping a batch is strictly better
        // than surfacing a failure into the conversation.
      }
    }
  } finally {
    flushing = false
    if (queue.length > 0) schedule()
  }
}

function optionalId(value?: string): string | undefined {
  const clean = (value ?? '').trim()
  if (!clean) return undefined
  return /^[A-Za-z0-9_:-]+$/.test(clean) ? clean.slice(0, 128) : undefined
}

function normalizeRevision(value?: number): number | undefined {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) return undefined
  return value
}

function normalizeDuration(value?: number): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return undefined
  return Math.round(value * 100) / 100
}

function sanitizeAttributes(attributes?: Record<string, unknown>): Record<string, unknown> {
  if (!attributes) return {}
  const result: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(attributes).slice(0, MAX_ATTRIBUTES)) {
    if (SECRET_KEY.test(key)) continue
    if (value === undefined || value === null) continue
    if (typeof value === 'string') {
      const clean = value.trim()
      if (clean) result[key] = clean.length > MAX_STRING ? `${clean.slice(0, MAX_STRING)}…` : clean
      continue
    }
    if (typeof value === 'number' && Number.isFinite(value)) {
      result[key] = value
      continue
    }
    if (typeof value === 'boolean') result[key] = value
  }
  return result
}

if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', () => flushClientEvents())
}
