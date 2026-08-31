import { api } from '../../shared/api/client'
import type { IngestInput, IngestResult, RagHealth, SearchInput, SearchResult } from './types'

export async function getRagHealth(): Promise<RagHealth> {
  return api.get<RagHealth>('/rag/health')
}

export async function ingestText(input: IngestInput): Promise<IngestResult> {
  if (input.file) {
    const form = new FormData()
    form.append('file', input.file)
    form.append('collection', input.collection)
    return api.post<IngestResult>('/rag/ingest/file', form)
  }
  return api.post<IngestResult>('/rag/ingest', {
    source_name: input.sourceName,
    collection: input.collection,
    content: input.content,
    content_type: 'text/markdown',
  })
}

export async function searchDocuments(input: SearchInput): Promise<SearchResult> {
  return api.post<SearchResult>('/rag/search', {
    query: input.query,
    collection: input.collection,
    top_k: input.topK,
  })
}
