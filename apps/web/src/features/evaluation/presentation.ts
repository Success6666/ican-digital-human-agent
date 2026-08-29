import type { EvaluationOverview, EvaluationOverviewWire, EvaluationRunWire } from './types'

export function normalizeOverview(payload: EvaluationOverviewWire | null): EvaluationOverview | null {
  if (!payload) return null
  const latency = asRecord(payload.latency)
  const source = String(payload.source ?? '').toLowerCase() === 'empty' ? 'empty' : 'evaluation'
  return {
    datasetCount: numberOf(payload.datasetCount ?? payload.dataset_count),
    caseCount: numberOf(payload.caseCount ?? payload.case_count),
    totalRuns: numberOf(payload.totalRuns ?? payload.total_runs),
    totalTokens: source === 'empty' ? undefined : numberOf(payload.totalTokens ?? payload.total_tokens),
    inputTokens: numberOf(payload.inputTokens ?? payload.input_tokens),
    outputTokens: numberOf(payload.outputTokens ?? payload.output_tokens),
    totalCost: source === 'empty' ? undefined : costAmount(payload.cost) ?? numberOf(payload.totalCost ?? payload.total_cost),
    currency: typeof payload.currency === 'string' ? payload.currency : costCurrency(payload.cost) ?? 'CNY',
    taskSuccessRate: source === 'empty' ? undefined : ratio(payload.taskSuccessRate ?? payload.task_success_rate),
    toolCallAccuracy: source === 'empty' ? undefined : ratio(payload.toolCallAccuracy ?? payload.tool_call_accuracy),
    resultCorrectness: source === 'empty' ? undefined : ratio(payload.resultCorrectness ?? payload.result_correctness),
    resultConsistency: source === 'empty' ? undefined : ratio(payload.resultConsistency ?? payload.result_consistency),
    groundedness: source === 'empty' ? undefined : ratio(payload.groundedness ?? payload.factualGroundedness ?? payload.factual_groundedness),
    promptInjectionProtection: source === 'empty' ? undefined : ratio(payload.promptInjectionProtection ?? payload.prompt_injection_protection),
    agentLatencyMs: source === 'empty' ? undefined : numberOf(payload.agentLatencyMs ?? payload.agent_latency_ms ?? latency.agent_ms),
    digitalHumanLatencyMs: source === 'empty' ? undefined : numberOf(payload.digitalHumanLatencyMs ?? payload.digital_human_latency_ms ?? latency.digital_human_ms),
    totalLatencyMs: source === 'empty' ? undefined : numberOf(payload.totalLatencyMs ?? payload.total_latency_ms ?? latency.total_ms),
    agentLatencyP50Ms: source === 'empty' ? undefined : numberOf(payload.agentLatencyP50Ms ?? payload.agent_latency_p50_ms),
    agentLatencyP95Ms: source === 'empty' ? undefined : numberOf(payload.agentLatencyP95Ms ?? payload.agent_latency_p95_ms),
    digitalHumanLatencyP50Ms: source === 'empty' ? undefined : numberOf(payload.digitalHumanLatencyP50Ms ?? payload.digital_human_latency_p50_ms),
    digitalHumanLatencyP95Ms: source === 'empty' ? undefined : numberOf(payload.digitalHumanLatencyP95Ms ?? payload.digital_human_latency_p95_ms),
    source,
  }
}

export function deriveOverview(runs: EvaluationRunWire[], fallbackRuns = 0): EvaluationOverview | null {
  if (runs.length === 0 && fallbackRuns === 0) return null
  const successful = runs.filter((run) => ['ok', 'success', 'completed', 'passed'].includes(String(run.status ?? '').toLowerCase())).length
  const durations = runs.map((run) => numberOf(run.durationMs ?? run.duration_ms)).filter((value): value is number => value !== undefined)
  const tokens = runs.map((run) => numberOf(run.totalTokens ?? run.total_tokens)).filter((value): value is number => value !== undefined)
  return {
    totalRuns: runs.length || fallbackRuns,
    totalTokens: tokens.length ? tokens.reduce((sum, value) => sum + value, 0) : undefined,
    totalCost: sumDefined(runs.map((run) => numberOf(run.cost))),
    currency: 'CNY',
    taskSuccessRate: runs.length ? successful / runs.length : undefined,
    totalLatencyMs: durations.length ? durations.reduce((sum, value) => sum + value, 0) / durations.length : undefined,
    source: 'telemetry',
  }
}

export function percent(value?: number): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return '暂无数据'
  const normalized = value > 1 ? value : value * 100
  return `${Math.max(0, Math.min(100, normalized)).toFixed(1)}%`
}

export function integer(value?: number): string {
  return value === undefined || !Number.isFinite(value) ? '暂无数据' : Math.round(value).toLocaleString('zh-CN')
}

export function money(value?: number, currency = 'CNY'): string {
  if (value === undefined || !Number.isFinite(value)) return '暂无数据'
  try {
    return new Intl.NumberFormat('zh-CN', { style: 'currency', currency, maximumFractionDigits: 4 }).format(value)
  } catch {
    return `${value.toFixed(4)} ${currency}`
  }
}

export function duration(value?: number): string {
  if (value === undefined || !Number.isFinite(value)) return '暂无数据'
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(2)} s`
}

function ratio(value: unknown): number | undefined {
  const number = numberOf(value)
  if (number === undefined) return undefined
  return number > 1 ? number / 100 : number
}

function numberOf(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function costAmount(value: unknown): number | undefined {
  return numberOf(value) ?? numberOf(asRecord(value).amount)
}

function costCurrency(value: unknown): string | undefined {
  const currency = asRecord(value).currency
  return typeof currency === 'string' ? currency : undefined
}

function sumDefined(values: Array<number | undefined>): number | undefined {
  const defined = values.filter((value): value is number => value !== undefined)
  return defined.length ? defined.reduce((sum, value) => sum + value, 0) : undefined
}
