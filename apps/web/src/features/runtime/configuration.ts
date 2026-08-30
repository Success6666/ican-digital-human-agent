import { useCallback, useEffect, useState } from 'react'
import { api } from '../../shared/api/client'

export interface ConfigurationService {
  configured?: boolean
  detail?: string
  mode?: string
  provider?: string
  parser?: string
  enabled?: boolean
  localModels?: string[]
  artifactsConfigured?: boolean
  ocrBackend?: string
  maxResultBytes?: number
  localFallback?: boolean
  [key: string]: unknown
}

export interface RuntimeConfiguration {
  environment?: string
  defaultProvider?: string
  session?: { ttlSeconds?: number; cleanupIntervalSeconds?: number }
  llm?: ConfigurationService
  embedding?: ConfigurationService
  rag?: ConfigurationService
  mcp?: ConfigurationService
  observability?: ConfigurationService
  [key: string]: unknown
}

export function useConfiguration() {
  const [configuration, setConfiguration] = useState<RuntimeConfiguration | null>(null)
  const [isLoading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setConfiguration(await api.get<RuntimeConfiguration>('/configuration'))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '配置状态暂不可用')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])
  return { configuration, isLoading, error, refresh }
}
