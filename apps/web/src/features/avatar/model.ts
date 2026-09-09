import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AvatarSession, ProviderName, ProviderStatus } from '../../shared/api/types'
import * as avatarApi from './api'
import type { ProviderWire } from './api'
import { capabilityNames } from './capabilities'

const providerOrder: ProviderName[] = ['mock', 'aliyun', 'mofa', 'iflytek', 'fay']
const preferredRuntimeOrder: ProviderName[] = ['mofa', 'aliyun', 'iflytek', 'fay', 'mock']
const providerLabels: Record<string, string> = {
  mock: 'Mock Runtime',
  aliyun: '阿里云数字人',
  mofa: '魔珐星云',
  iflytek: '讯飞数字人',
  fay: 'Fay Runtime',
}

function normalizeProviders(items: ProviderWire[]): ProviderStatus[] {
  const mapped = items.map((item) => {
    const name = item.name || item.provider || 'unknown'
    const status = (item.status || '').toLowerCase()
    const available = item.available ?? !['offline', 'unavailable', 'error'].includes(status)
    const capabilities = capabilityNames(item.capabilities)
    return {
      name,
      label: item.label || providerLabels[name] || name,
      description: item.description || item.detail,
      configured: item.configured ?? available,
      available,
      default: item.default,
      capabilities,
      status,
    }
  })
  return mapped.sort((a, b) => {
    const ai = providerOrder.indexOf(a.name)
    const bi = providerOrder.indexOf(b.name)
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
  })
}

export function useAvatar() {
  const [providers, setProviders] = useState<ProviderStatus[]>([])
  const [selectedProvider, setSelectedProvider] = useState<ProviderName>('mock')
  const [session, setSession] = useState<AvatarSession | null>(null)
  const sessionRef = useRef<AvatarSession | null>(null)
  const createInFlightRef = useRef<Promise<AvatarSession> | null>(null)
  const selectionInitializedRef = useRef(false)
  const [isLoading, setLoading] = useState(true)
  const [isCreating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadProviders = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const next = normalizeProviders(await avatarApi.listProviders())
      setProviders(next)
      if (next.length) {
        setSelectedProvider((current) => {
          if (selectionInitializedRef.current && next.some((provider) => provider.name === current && provider.available && provider.configured)) return current
          const preferred = next.find((provider) => provider.default && provider.available && provider.configured)
            ?? preferredRuntimeOrder.map((name) => next.find((provider) => provider.name === name && provider.available && provider.configured)).find(Boolean)
          selectionInitializedRef.current = true
          return preferred?.name ?? next[0].name
        })
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Provider 列表加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadProviders() }, [loadProviders])

  useEffect(() => {
    sessionRef.current = session
  }, [session])

  const create = useCallback(async (provider?: ProviderName) => {
    if (createInFlightRef.current) return createInFlightRef.current
    setCreating(true)
    setError(null)
    const requestedProvider = provider ?? selectedProvider
    const request = (async () => {
      try {
        const current = sessionRef.current
        if (current) await avatarApi.closeSession(current.sessionId).catch(() => undefined)
        const next = await avatarApi.createSession(requestedProvider)
        sessionRef.current = next
        setSession(next)
        selectionInitializedRef.current = true
        setSelectedProvider(next.provider)
        return next
      } catch (cause) {
        const message = cause instanceof Error ? cause.message : '会话创建失败'
        setError(message)
        throw cause
      }
    })()
    createInFlightRef.current = request
    void request.then(
      () => {
        if (createInFlightRef.current === request) createInFlightRef.current = null
        setCreating(false)
      },
      () => {
        if (createInFlightRef.current === request) createInFlightRef.current = null
        setCreating(false)
      },
    )
    return request
  }, [selectedProvider])

  const close = useCallback(async () => {
    if (!session) return
    const current = session
    sessionRef.current = null
    setSession(null)
    try {
      await avatarApi.closeSession(current.sessionId)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '会话关闭失败')
    }
  }, [session])

  const selected = useMemo(
    () => providers.find((provider) => provider.name === selectedProvider) ?? null,
    [providers, selectedProvider],
  )

  const chooseProvider = useCallback((provider: ProviderName) => {
    selectionInitializedRef.current = true
    setSelectedProvider(provider)
  }, [])

  return {
    providers,
    selected,
    selectedProvider,
    setSelectedProvider: chooseProvider,
    session,
    isLoading,
    isCreating,
    error,
    clearError: () => setError(null),
    loadProviders,
    create,
    close,
  }
}
