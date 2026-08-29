export interface RagHealth {
  status?: string
  documents?: number
  docling_available?: boolean | null
  doclingAvailable?: boolean | null
}

export interface IngestInput {
  sourceName: string
  collection: string
  content: string
}

export interface IngestResult {
  document_id?: string
  source_name?: string
  collection?: string
  parser?: string
  chunk_count?: number
}

export interface SearchInput {
  query: string
  collection: string
  topK: number
}

export interface SearchHit {
  score?: number
  chunk?: {
    text?: string
    ordinal?: number
    metadata?: Record<string, unknown>
  }
}

export interface SearchResult {
  query?: string
  collection?: string
  hits?: SearchHit[]
}
