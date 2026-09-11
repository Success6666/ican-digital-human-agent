export interface RagHealth {
  status?: string
  documents?: number
  chunks?: number
  storage?: string
  collections?: RagCollectionStatistics[]
  docling_available?: boolean | null
  doclingAvailable?: boolean | null
  /** False when the configured OCR engine cannot be constructed (missing runtime). */
  docling_ocr_ready?: boolean | null
  /** Human readable reason the OCR engine is unusable, when it is. */
  docling_ocr_error?: string | null
}

export interface RagCollectionStatistics {
  name: string
  documents: number
  chunks: number
}

export interface IngestInput {
  sourceName: string
  collection: string
  content: string
  file?: File
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
