import { api } from '../../shared/api/client'
import type { TelemetryEvent } from './types'

interface RecentEventsResponse {
  events?: TelemetryEvent[]
}

export async function getRecentEvents(limit = 200): Promise<TelemetryEvent[]> {
  const safeLimit = Math.max(1, Math.min(limit, 500))
  const response = await api.get<TelemetryEvent[] | RecentEventsResponse>(`/observability/recent?limit=${safeLimit}`)
  return Array.isArray(response) ? response : response.events ?? []
}
