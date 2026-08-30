export interface EvaluationOverviewWire {
  source?: 'evaluation' | 'empty' | string
  dataset_count?: number
  datasetCount?: number
  case_count?: number
  caseCount?: number
  total_runs?: number
  totalRuns?: number
  total_tokens?: number
  totalTokens?: number
  input_tokens?: number
  inputTokens?: number
  output_tokens?: number
  outputTokens?: number
  total_cost?: number
  totalCost?: number
  cost?: number | { amount?: number; currency?: string }
  currency?: string
  task_success_rate?: number
  taskSuccessRate?: number
  tool_call_accuracy?: number
  toolCallAccuracy?: number
  result_correctness?: number
  resultCorrectness?: number
  result_consistency?: number
  resultConsistency?: number
  groundedness?: number
  factual_groundedness?: number
  factualGroundedness?: number
  prompt_injection_protection?: number
  promptInjectionProtection?: number
  agent_latency_ms?: number
  agentLatencyMs?: number
  digital_human_latency_ms?: number
  digitalHumanLatencyMs?: number
  total_latency_ms?: number
  totalLatencyMs?: number
  agent_latency_p50_ms?: number
  agentLatencyP50Ms?: number
  agent_latency_p95_ms?: number
  agentLatencyP95Ms?: number
  digital_human_latency_p50_ms?: number
  digitalHumanLatencyP50Ms?: number
  digital_human_latency_p95_ms?: number
  digitalHumanLatencyP95Ms?: number
  first_event_latency_ms?: number
  firstEventLatencyMs?: number
  first_visible_latency_ms?: number
  firstVisibleLatencyMs?: number
  cancellation_latency_ms?: number
  cancellationLatencyMs?: number
  first_event_latency_p50_ms?: number
  firstEventLatencyP50Ms?: number
  first_event_latency_p95_ms?: number
  firstEventLatencyP95Ms?: number
  first_visible_latency_p50_ms?: number
  firstVisibleLatencyP50Ms?: number
  first_visible_latency_p95_ms?: number
  firstVisibleLatencyP95Ms?: number
  cancellation_latency_p50_ms?: number
  cancellationLatencyP50Ms?: number
  cancellation_latency_p95_ms?: number
  cancellationLatencyP95Ms?: number
  cancellation_rate?: number
  cancellationRate?: number
  latency?: { agent_ms?: number; digital_human_ms?: number; total_ms?: number }
  [key: string]: unknown
}

export interface EvaluationDatasetWire {
  id?: string
  version?: string
  name?: string
  description?: string
  source?: string
  case_count?: number
  caseCount?: number
  sample_count?: number
  sampleCount?: number
  dimensions?: string[]
  created_at?: string
  createdAt?: string
  status?: string
  updated_at?: string
  updatedAt?: string
  [key: string]: unknown
}

export interface EvaluationRunWire {
  id?: string
  name?: string
  dataset_id?: string
  datasetId?: string
  status?: string
  success_rate?: number
  successRate?: number
  total_tokens?: number
  totalTokens?: number
  cost?: number
  currency?: string
  input_tokens?: number
  inputTokens?: number
  output_tokens?: number
  outputTokens?: number
  agent_latency_ms?: number
  agentLatencyMs?: number
  digital_human_latency_ms?: number
  digitalHumanLatencyMs?: number
  first_event_latency_ms?: number
  firstEventLatencyMs?: number
  first_visible_latency_ms?: number
  firstVisibleLatencyMs?: number
  cancellation_latency_ms?: number
  cancellationLatencyMs?: number
  duration_ms?: number
  durationMs?: number
  scores?: Record<string, { score?: number; label?: string; detail?: string }>
  input_preview?: string
  output_preview?: string
  created_at?: string
  createdAt?: string
  [key: string]: unknown
}

export interface EvaluationOverview {
  datasetCount?: number
  caseCount?: number
  totalRuns?: number
  totalTokens?: number
  inputTokens?: number
  outputTokens?: number
  totalCost?: number
  currency: string
  taskSuccessRate?: number
  toolCallAccuracy?: number
  resultCorrectness?: number
  resultConsistency?: number
  groundedness?: number
  promptInjectionProtection?: number
  agentLatencyMs?: number
  digitalHumanLatencyMs?: number
  totalLatencyMs?: number
  source: 'evaluation' | 'telemetry' | 'empty'
  agentLatencyP50Ms?: number
  agentLatencyP95Ms?: number
  digitalHumanLatencyP50Ms?: number
  digitalHumanLatencyP95Ms?: number
  firstEventLatencyMs?: number
  firstVisibleLatencyMs?: number
  cancellationLatencyMs?: number
  firstEventLatencyP50Ms?: number
  firstEventLatencyP95Ms?: number
  firstVisibleLatencyP50Ms?: number
  firstVisibleLatencyP95Ms?: number
  cancellationLatencyP50Ms?: number
  cancellationLatencyP95Ms?: number
  cancellationRate?: number
}

export interface EvaluationDataState {
  overview: EvaluationOverview | null
  datasets: EvaluationDatasetWire[]
  runs: EvaluationRunWire[]
  unavailable: string[]
}
