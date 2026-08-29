import { ApiError, api } from '../../shared/api/client'
import type { EvaluationDatasetWire, EvaluationOverviewWire, EvaluationRunWire } from './types'

interface ListResponse<T> { items?: T[]; datasets?: T[]; runs?: T[] }

export async function getOverview(): Promise<EvaluationOverviewWire | null> {
  try {
    return await api.get<EvaluationOverviewWire>('/evaluation/overview')
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) return null
    throw cause
  }
}

export async function getDatasets(): Promise<EvaluationDatasetWire[] | null> {
  try {
    const response = await api.get<EvaluationDatasetWire[] | ListResponse<EvaluationDatasetWire>>('/evaluation/datasets')
    if (Array.isArray(response)) return response
    return response.datasets ?? response.items ?? []
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) return null
    throw cause
  }
}

export async function getRuns(): Promise<EvaluationRunWire[] | null> {
  try {
    const response = await api.get<EvaluationRunWire[] | ListResponse<EvaluationRunWire>>('/evaluation/runs')
    if (Array.isArray(response)) return response
    return response.runs ?? response.items ?? []
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) return null
    throw cause
  }
}
