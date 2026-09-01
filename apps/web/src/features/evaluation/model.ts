import { useCallback, useEffect, useState } from 'react'
import * as evaluationApi from './api'
import { normalizeOverview } from './presentation'
import type { EvaluationDataState } from './types'

const initialState: EvaluationDataState = { overview: null, datasets: [], runs: [], unavailable: [] }

export function useEvaluationData() {
  const [state, setState] = useState<EvaluationDataState>(initialState)
  const [isLoading, setLoading] = useState(true)
  const [isRefreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [runningDatasetId, setRunningDatasetId] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setRefreshing(true)
    setError(null)
    const [overview, datasets, runs] = await Promise.allSettled([evaluationApi.getOverview(), evaluationApi.getDatasets(), evaluationApi.getRuns()])
    const unavailable: string[] = []
    if (overview.status === 'rejected' || (overview.status === 'fulfilled' && overview.value === null)) unavailable.push('指标接口')
    if (datasets.status === 'rejected' || (datasets.status === 'fulfilled' && datasets.value === null)) unavailable.push('数据集接口')
    if (runs.status === 'rejected' || (runs.status === 'fulfilled' && runs.value === null)) unavailable.push('评测运行接口')
    setState({
      overview: overview.status === 'fulfilled' ? normalizeOverview(overview.value) : null,
      datasets: datasets.status === 'fulfilled' && datasets.value ? datasets.value : [],
      runs: runs.status === 'fulfilled' && runs.value ? runs.value : [],
      unavailable,
    })
    if (unavailable.length) setError(`部分评测数据暂不可用：${unavailable.join('、')}`)
    setLoading(false)
    setRefreshing(false)
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  const runDataset = useCallback(async (datasetId: string) => {
    setRunningDatasetId(datasetId)
    setError(null)
    try {
      await evaluationApi.runDataset(datasetId)
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '评测运行失败')
      throw cause
    } finally {
      setRunningDatasetId(null)
    }
  }, [refresh])

  return { ...state, isLoading, isRefreshing, runningDatasetId, error, refresh, runDataset }
}
