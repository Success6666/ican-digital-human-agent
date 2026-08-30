import { BadgeDollarSign, CheckCheck, Coins, Gauge, ShieldAlert, Target, Timer, Wrench } from 'lucide-react'
import type { EvaluationOverview } from '../types'
import { duration, integer, money, percent } from '../presentation'
import { MetricTile } from '../../../shared/components/MetricTile'

interface EvaluationMetricsProps {
  overview: EvaluationOverview | null
}

export function EvaluationMetrics({ overview }: EvaluationMetricsProps) {
  const value = overview ?? { currency: 'CNY', source: 'evaluation' as const }
  return (
    <div className="metric-grid metric-grid--four evaluation-metrics">
      <MetricTile label="任务成功率" value={percent(value.taskSuccessRate)} detail="通过 / 总任务" icon={<Target size={15} />} tone={value.taskSuccessRate === undefined ? 'neutral' : 'accent'} />
      <MetricTile label="工具调用准确率" value={percent(value.toolCallAccuracy)} detail="工具选择 precision / recall" icon={<Wrench size={15} />} tone="neutral" />
      <MetricTile label="结果正确性" value={percent(value.resultCorrectness)} detail="答案质量评分" icon={<CheckCheck size={15} />} tone="neutral" />
      <MetricTile label="结果一致性" value={percent(value.resultConsistency)} detail="多次运行稳定度" icon={<Gauge size={15} />} tone="neutral" />
      <MetricTile label="事实有据性" value={percent(value.groundedness)} detail="引用上下文支持度" icon={<ShieldAlert size={15} />} tone="neutral" />
      <MetricTile label="提示词注入防护" value={percent(value.promptInjectionProtection)} detail="安全样本拦截率" icon={<ShieldAlert size={15} />} tone="warning" />
      <MetricTile label="Token 用量" value={integer(value.totalTokens)} detail={`${integer(value.inputTokens)} 输入 · ${integer(value.outputTokens)} 输出`} icon={<Coins size={15} />} tone="neutral" />
      <MetricTile label="累计成本" value={money(value.totalCost, value.currency)} detail={value.totalRuns === undefined ? '等待评测数据' : `${integer(value.totalRuns)} 次运行`} icon={<BadgeDollarSign size={15} />} tone="warning" />
      <MetricTile label="Agent 延迟" value={duration(value.agentLatencyMs)} detail={latencyDetail(value.agentLatencyP50Ms, value.agentLatencyP95Ms, '编排与工具阶段')} icon={<Timer size={15} />} tone="neutral" />
      <MetricTile label="数字人延迟" value={duration(value.digitalHumanLatencyMs)} detail={latencyDetail(value.digitalHumanLatencyP50Ms, value.digitalHumanLatencyP95Ms, 'Provider 分段')} icon={<Timer size={15} />} tone="neutral" />
      <MetricTile label="首事件延迟" value={duration(value.firstEventLatencyMs)} detail={latencyDetail(value.firstEventLatencyP50Ms, value.firstEventLatencyP95Ms, '服务端首个事件')} icon={<Timer size={15} />} tone="accent" />
      <MetricTile label="首可见延迟" value={duration(value.firstVisibleLatencyMs)} detail={latencyDetail(value.firstVisibleLatencyP50Ms, value.firstVisibleLatencyP95Ms, '服务端首个可见事件')} icon={<Timer size={15} />} tone="accent" />
      <MetricTile label="取消延迟" value={duration(value.cancellationLatencyMs)} detail={`${latencyDetail(value.cancellationLatencyP50Ms, value.cancellationLatencyP95Ms, '改口 / 停止到生效')} · ${value.cancellationRate === undefined ? '取消率暂无数据' : `取消率 ${percent(value.cancellationRate)}`}`} icon={<Timer size={15} />} tone="warning" />
      <MetricTile label="端到端延迟" value={duration(value.totalLatencyMs)} detail="请求总耗时" icon={<Timer size={15} />} tone="accent" />
      <MetricTile label="统计来源" value={value.source === 'evaluation' ? '评测数据' : '遥测估算'} detail="仅展示已确认指标" icon={<Gauge size={15} />} tone="neutral" />
    </div>
  )
}

function latencyDetail(p50?: number, p95?: number, fallback = '阶段耗时'): string {
  const values = [p50, p95].map((item) => item !== undefined ? duration(item) : '暂无数据')
  return `${fallback} · p50 ${values[0]} · p95 ${values[1]}`
}
