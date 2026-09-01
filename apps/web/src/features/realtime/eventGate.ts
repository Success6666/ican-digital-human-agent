import type { RealtimeInboundEvent } from './types'

/** Drop late or duplicated realtime events from a superseded utterance. */
export class RealtimeEventGate {
  private readonly eventIds = new Set<string>()
  private readonly maxEventIds: number
  private revision = 0
  private runId?: string
  private utteranceId?: string
  private sequence?: number
  private readonly completedRuns = new Set<string>()

  constructor(maxEventIds = 512) {
    this.maxEventIds = Math.max(16, Math.floor(maxEventIds))
  }

  get currentRevision(): number { return this.revision }
  get currentUtteranceId(): string | undefined { return this.utteranceId }

  reset(utteranceId: string, revision: number): void {
    this.eventIds.clear()
    this.utteranceId = utteranceId
    this.revision = revision
    this.runId = undefined
    this.sequence = undefined
    this.completedRuns.clear()
  }

  setRun(runId?: string): void {
    if (runId && !this.completedRuns.has(runId)) this.runId = runId
  }

  markRunTerminal(runId?: string): void {
    if (!runId) return
    this.completedRuns.add(runId)
    if (this.completedRuns.size > 128) {
      const oldest = this.completedRuns.values().next().value as string | undefined
      if (oldest) this.completedRuns.delete(oldest)
    }
    if (this.runId === runId) this.runId = undefined
  }

  accept(event: RealtimeInboundEvent): RealtimeInboundEvent | null {
    const eventRevision = finiteRevision(event.revision)
    if (eventRevision !== undefined && eventRevision < this.revision) return null
    if (eventRevision !== undefined && eventRevision > this.revision) {
      // A newer revision starts a new generation. Clear all run/sequence
      // state before validating the event so no old event can leak across it.
      this.revision = eventRevision
      this.runId = undefined
      this.sequence = undefined
      this.eventIds.clear()
      // Some server events carry only the new revision. Keep the current
      // utterance in that case so an old event cannot become unscoped.
      if (event.utteranceId) this.utteranceId = event.utteranceId
    }
    if (event.utteranceId && this.utteranceId && event.utteranceId !== this.utteranceId) return null
    const type = String(event.type ?? '').toLowerCase()
    if (event.runId && this.completedRuns.has(event.runId) && isRunScoped(type)) return null
    if (event.runId && this.runId && event.runId !== this.runId && isRunScoped(type)) return null
    if (event.eventId && this.eventIds.has(event.eventId)) return null
    if (event.seq !== undefined && this.sequence !== undefined && event.seq <= this.sequence) return null
    if (event.eventId) this.remember(event.eventId)
    if (event.seq !== undefined) this.sequence = event.seq
    if (event.runId && !this.runId) this.runId = event.runId
    return event
  }

  private remember(eventId: string): void {
    this.eventIds.add(eventId)
    while (this.eventIds.size > this.maxEventIds) {
      const oldest = this.eventIds.values().next().value as string | undefined
      if (oldest === undefined) break
      this.eventIds.delete(oldest)
    }
  }
}

function finiteRevision(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : undefined
}

function isRunScoped(type: string): boolean {
  return ['run_started', 'start', 'filler', 'intent', 'tool_disclosure', 'security', 'rag', 'tool', 'delta', 'provider', 'audio_queue', 'interrupted', 'run_done', 'done'].includes(type)
}
