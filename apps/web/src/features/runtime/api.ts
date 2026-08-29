import { api } from '../../shared/api/client'

export interface RagHealthWire {
  status?: string
  documents?: number
  docling_available?: boolean | null
  doclingAvailable?: boolean | null
  [key: string]: unknown
}

export interface ObservabilityHealthWire {
  status?: string
  backend?: string
  configured?: boolean
  buffered_events?: number
  bufferedEvents?: number
  last_error?: string | null
  lastError?: string | null
  [key: string]: unknown
}

export interface RuntimeHealthWire {
  rag: RagHealthWire | null
  observability: ObservabilityHealthWire | null
}

export async function getRuntimeHealth(): Promise<RuntimeHealthWire> {
  const [rag, observability] = await Promise.allSettled([
    api.get<RagHealthWire>('/rag/health'),
    api.get<ObservabilityHealthWire>('/observability/health'),
  ])

  return {
    rag: rag.status === 'fulfilled' ? rag.value : null,
    observability: observability.status === 'fulfilled' ? observability.value : null,
  }
}
