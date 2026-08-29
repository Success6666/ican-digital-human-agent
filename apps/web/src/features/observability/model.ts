import { useCallback, useEffect, useState } from 'react'
import * as observabilityApi from './api'
import type { TelemetryEvent } from './types'

export function useObservabilityEvents(limit = 200) {
  const [events, setEvents] = useState<TelemetryEvent[]>([])
  const [isLoading, setLoading] = useState(true)
  const [isRefreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setRefreshing(true)
    setError(null)
    try {
      setEvents(await observabilityApi.getRecentEvents(limit))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '暂时无法读取运行记录')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [limit])

  useEffect(() => { void refresh() }, [refresh])

  return { events, isLoading, isRefreshing, error, refresh }
}
