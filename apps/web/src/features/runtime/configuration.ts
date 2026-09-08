import { useCallback, useEffect, useState } from 'react'
import { api } from '../../shared/api/client'

export interface ConfigurationService {
  configured?: boolean
  detail?: string
  mode?: string
  provider?: string
  parser?: string
  storage?: string
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
  mofa?: {
    enabled?: boolean
    configured?: boolean
    appId?: string
    appSecret?: string
    authorization?: string
    gatewayUrl?: string
    sdkUrl?: string
    cryptoUrl?: string
    emotionEnabled?: boolean
    detail?: string
  }
  aliyun?: {
    enabled?: boolean
    configured?: boolean
    baseUrl?: string
    appId?: string
    instanceId?: string
    accessKeyId?: string
    accessKeySecret?: string
    detail?: string
  }
  iflytek?: {
    enabled?: boolean
    configured?: boolean
    gatewayUrl?: string
    appId?: string
    apiKey?: string
    apiSecret?: string
    detail?: string
  }
  docling?: ConfigurationService
  futureagi?: ConfigurationService
  [key: string]: unknown
}

export interface RuntimeConfigurationPatch {
  defaultProvider?: string
  session?: { ttlSeconds?: number; cleanupIntervalSeconds?: number }
  mofa?: {
    enabled?: boolean
    appId?: string
    appSecret?: string
    authorization?: string
    gatewayUrl?: string
    sdkUrl?: string
    cryptoUrl?: string
    emotionEnabled?: boolean
  }
  aliyun?: {
    enabled?: boolean
    baseUrl?: string
    appId?: string
    instanceId?: string
    accessKeyId?: string
    accessKeySecret?: string
  }
  iflytek?: {
    enabled?: boolean
    gatewayUrl?: string
    appId?: string
    apiKey?: string
    apiSecret?: string
  }
  llm?: {
    enabled?: boolean
    provider?: string
    baseUrl?: string
    apiKey?: string
    model?: string
    temperature?: number
    maxTokens?: number
  }
  embedding?: {
    enabled?: boolean
    provider?: string
    baseUrl?: string
    apiKey?: string
    model?: string
    dimensions?: number
  }
  docling?: {
    enabled?: boolean
    artifactsPath?: string
    ocrBackend?: string
    ocrLanguages?: string[]
    doOcr?: boolean
    doTableStructure?: boolean
    tableMode?: string
    maxConcurrency?: number
  }
  futureagi?: {
    enabled?: boolean
    endpoint?: string
    apiKey?: string
    secretKey?: string
    project?: string
  }
}

export function useConfiguration() {
  const [configuration, setConfiguration] = useState<RuntimeConfiguration | null>(null)
  const [isLoading, setLoading] = useState(true)
  const [isSaving, setSaving] = useState(false)
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

  const save = useCallback(async (payload: RuntimeConfigurationPatch) => {
    setSaving(true)
    setError(null)
    try {
      const updated = await api.patch<RuntimeConfiguration>('/configuration', payload)
      setConfiguration(updated)
      return updated
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : '配置保存失败'
      setError(message)
      throw cause
    } finally {
      setSaving(false)
    }
  }, [])

  return { configuration, isLoading, isSaving, error, refresh, save }
}
