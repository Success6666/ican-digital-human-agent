import { useCallback, useEffect, useState } from 'react'
import * as ragApi from './api'
import type { IngestInput, IngestResult, RagHealth, SearchHit, SearchInput } from './types'

export function useRagWorkspace() {
  const [health, setHealth] = useState<RagHealth | null>(null)
  const [hits, setHits] = useState<SearchHit[]>([])
  const [ingestResult, setIngestResult] = useState<IngestResult | null>(null)
  const [isLoading, setLoading] = useState(true)
  const [isBusy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setHealth(await ragApi.getRagHealth())
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法读取 RAG 状态')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  const ingest = useCallback(async (input: IngestInput) => {
    setBusy(true)
    setError(null)
    try {
      const result = await ragApi.ingestText(input)
      setIngestResult(result)
      await refresh()
      return result
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : '文档入库失败'
      setError(message)
      throw cause
    } finally {
      setBusy(false)
    }
  }, [refresh])

  const search = useCallback(async (input: SearchInput) => {
    setBusy(true)
    setError(null)
    try {
      const result = await ragApi.searchDocuments(input)
      const nextHits = result.hits ?? []
      setHits(nextHits)
      return nextHits
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : '检索失败'
      setError(message)
      throw cause
    } finally {
      setBusy(false)
    }
  }, [])

  return { health, hits, ingestResult, isLoading, isBusy, error, refresh, ingest, search, clearError: () => setError(null) }
}
