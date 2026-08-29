import { useCallback, useEffect, useRef, useState } from 'react'
import * as runtimeApi from './api'

export type RuntimeStatus = 'online' | 'degraded' | 'offline' | 'pending'

export interface RuntimeServiceState {
  status: RuntimeStatus
  label: string
  detail?: string
  documents?: number
  backend?: string
  configured?: boolean
}

export interface RuntimeState {
  rag: RuntimeServiceState
  observability: RuntimeServiceState
  isLoading: boolean
  isRefreshing: boolean
  lastCheckedAt?: string
}

const pendingService = (label: string): RuntimeServiceState => ({
  status: 'pending',
  label,
  detail: '检查中',
})

const initialState: RuntimeState = {
  rag: pendingService('RAG'),
  observability: pendingService('遥测'),
  isLoading: true,
  isRefreshing: false,
}

function normalizeStatus(value: unknown, fallback: RuntimeStatus = 'offline'): RuntimeStatus {
  const status = String(value ?? '').toLowerCase()
  if (status === 'ok' || status === 'online' || status === 'ready' || status === 'healthy') return 'online'
  if (status === 'degraded' || status === 'partial') return 'degraded'
  if (status === 'pending' || status === 'starting') return 'pending'
  return fallback
}

function normalizeRag(payload: runtimeApi.RagHealthWire | null): RuntimeServiceState {
  if (!payload) return { status: 'offline', label: 'RAG', detail: '暂不可达' }
  const doclingAvailable = payload.docling_available ?? payload.doclingAvailable
  const status = doclingAvailable === false && normalizeStatus(payload.status) === 'online'
    ? 'degraded'
    : normalizeStatus(payload.status)
  return {
    status,
    label: 'RAG',
    detail: doclingAvailable === false ? '文本解析回退' : 'Docling 就绪',
    documents: typeof payload.documents === 'number' ? payload.documents : undefined,
  }
}

function normalizeObservability(payload: runtimeApi.ObservabilityHealthWire | null): RuntimeServiceState {
  if (!payload) return { status: 'offline', label: '遥测', detail: '暂不可达' }
  const backend = typeof payload.backend === 'string' ? payload.backend : undefined
  const configured = typeof payload.configured === 'boolean' ? payload.configured : undefined
  const status = normalizeStatus(payload.status)
  return {
    status,
    label: '遥测',
    detail: backend === 'futureagi' ? 'FutureAGI' : '本地缓冲',
    backend,
    configured,
  }
}

export function useRuntimeStatus(enabled = true) {
  const [state, setState] = useState<RuntimeState>(initialState)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const refresh = useCallback(async () => {
    if (!enabled) return
    setState((current) => ({ ...current, isRefreshing: true }))
    try {
      const health = await runtimeApi.getRuntimeHealth()
      if (!mountedRef.current) return
      setState({
        rag: normalizeRag(health.rag),
        observability: normalizeObservability(health.observability),
        isLoading: false,
        isRefreshing: false,
        lastCheckedAt: new Date().toISOString(),
      })
    } catch {
      if (!mountedRef.current) return
      setState({
        rag: { status: 'offline', label: 'RAG', detail: '暂不可达' },
        observability: { status: 'offline', label: '遥测', detail: '暂不可达' },
        isLoading: false,
        isRefreshing: false,
        lastCheckedAt: new Date().toISOString(),
      })
    }
  }, [enabled])

  useEffect(() => {
    if (!enabled) return
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 30_000)
    return () => window.clearInterval(timer)
  }, [enabled, refresh])

  return { ...state, refresh }
}
