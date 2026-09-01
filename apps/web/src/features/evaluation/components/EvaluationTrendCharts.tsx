import { ArrowUpRight, BadgeDollarSign, BarChart3, Clock3, Coins, ExternalLink } from 'lucide-react'
import type { EvaluationRunWire } from '../types'
import { duration, money, percent } from '../presentation'

interface EvaluationTrendChartsProps {
  runs: EvaluationRunWire[]
  currency?: string
  showingAll: boolean
  onSelectRun?: (run: EvaluationRunWire) => void
  onToggleAll: () => void
}

interface TrendMetric {
  key: string
  label: string
  color: string
  value: (run: EvaluationRunWire) => number | undefined
  format: (value: number) => string
}

interface TrendDefinition {
  id: string
  title: string
  description: string
  icon: typeof BarChart3
  metrics: TrendMetric[]
}

export function EvaluationTrendCharts({ runs, currency = 'CNY', showingAll, onSelectRun, onToggleAll }: EvaluationTrendChartsProps) {
  const definitions: TrendDefinition[] = [
    {
      id: 'quality',
      title: '质量走势',
      description: '最近十次任务成功、答案正确和事实有据的变化。',
      icon: BarChart3,
      metrics: [
        { key: 'success', label: '任务成功', color: 'var(--brand)', value: valueOf('successRate'), format: (value) => percent(value) },
        { key: 'correctness', label: '结果正确', color: 'var(--success)', value: scoreOf('result_correctness'), format: (value) => percent(value) },
        { key: 'groundedness', label: '事实有据', color: 'var(--warning)', value: scoreOf('factual_groundedness'), format: (value) => percent(value) },
      ],
    },
    {
      id: 'latency',
      title: '响应时延',
      description: '从请求到 Agent、数字人和首个可见结果的耗时。',
      icon: Clock3,
      metrics: [
        { key: 'total', label: '端到端', color: 'var(--brand)', value: valueOf('duration'), format: (value) => duration(value) },
        { key: 'agent', label: 'Agent', color: 'var(--success)', value: valueOf('agentLatency'), format: (value) => duration(value) },
        { key: 'visible', label: '首个可见', color: 'var(--warning)', value: valueOf('firstVisibleLatency'), format: (value) => duration(value) },
      ],
    },
    {
      id: 'tokens',
      title: 'Token 用量',
      description: '每次运行消耗的 Token，帮助识别上下文过长的样本。',
      icon: Coins,
      metrics: [
        { key: 'tokens', label: 'Token', color: 'var(--brand)', value: valueOf('tokens'), format: (value) => `${Math.round(value).toLocaleString('zh-CN')} Token` },
      ],
    },
    {
      id: 'cost',
      title: '运行成本',
      description: '每次运行的估算成本，帮助定位高成本请求。',
      icon: BadgeDollarSign,
      metrics: [
        { key: 'cost', label: '成本', color: 'var(--danger)', value: valueOf('cost'), format: (value) => money(value, currency) },
      ],
    },
  ]

  return (
    <section className="evaluation-trends" aria-labelledby="evaluation-trends-title">
      <div className="evaluation-section-heading">
        <div>
          <p className="panel-kicker">趋势判断</p>
          <h2 id="evaluation-trends-title">先看变化，再看证据</h2>
          <p>图表默认展示最近十次评测。点击数据点查看该轮详情，展开后可浏览全部已保留运行。</p>
        </div>
        <button className="secondary-button" type="button" onClick={onToggleAll} disabled={runs.length === 0}>
          <ExternalLink size={14} />
          {showingAll ? '收起全量数据' : `查看全量数据（${runs.length} 次）`}
        </button>
      </div>
      <div className="evaluation-trend-grid">
        {definitions.map((definition) => <TrendChart key={definition.id} definition={definition} runs={runs} onSelectRun={onSelectRun} />)}
      </div>
    </section>
  )
}

function TrendChart({ definition, runs, onSelectRun }: { definition: TrendDefinition; runs: EvaluationRunWire[]; onSelectRun?: (run: EvaluationRunWire) => void }) {
  const Icon = definition.icon
  const points = [...runs].reverse().slice(-10)
  const values = definition.metrics.flatMap((metric) => points.map(metric.value).filter((value): value is number => value !== undefined && Number.isFinite(value)))
  const hasData = values.length > 0
  const min = hasData ? Math.min(...values) : 0
  const max = hasData ? Math.max(...values) : 1
  const padding = min === max ? Math.max(1, Math.abs(min) * 0.08) : (max - min) * 0.12
  const low = Math.max(0, min - padding)
  const high = max + padding || 1
  const width = 720
  const height = 250
  const plot = { left: 46, right: 18, top: 18, bottom: 34 }
  const plotWidth = width - plot.left - plot.right
  const plotHeight = height - plot.top - plot.bottom
  const x = (index: number) => points.length <= 1 ? plot.left + plotWidth / 2 : plot.left + (index / (points.length - 1)) * plotWidth
  const y = (value: number) => plot.top + (1 - ((value - low) / (high - low || 1))) * plotHeight
  const ticks = [high, high - (high - low) / 2, low]

  return (
    <article className="evaluation-trend-panel work-panel">
      <header className="evaluation-trend-head">
        <div className="evaluation-trend-title"><span className="evaluation-trend-icon"><Icon size={16} /></span><div><h3>{definition.title}</h3><p>{definition.description}</p></div></div>
        <span className="trend-window">{points.length ? `近 ${points.length} 次` : '等待数据'}</span>
      </header>
      {!hasData ? <div className="evaluation-chart-empty"><BarChart3 size={20} /><strong>还没有可绘制的评测结果</strong><span>完成一次评测后，这里会显示可读趋势。</span></div> : <div className="evaluation-chart-wrap"><svg className="evaluation-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${definition.title}，展示最近 ${points.length} 次评测结果`}>
        {ticks.map((tick, index) => <g key={`tick-${index}`}><line x1={plot.left} x2={width - plot.right} y1={y(tick)} y2={y(tick)} className="chart-gridline" /><text x={plot.left - 8} y={y(tick) + 4} textAnchor="end" className="chart-axis-label">{formatAxisTick(definition.id, tick)}</text></g>)}
        {definition.metrics.map((metric) => {
          const line = points.map((run, index) => { const value = metric.value(run); return value === undefined ? null : `${x(index)},${y(value)}` }).filter(Boolean).join(' ')
          return <g key={metric.key}><polyline points={line} fill="none" stroke={metric.color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="chart-line" />{points.map((run, index) => { const value = metric.value(run); if (value === undefined) return null; return <circle key={`${metric.key}-${run.id ?? index}`} cx={x(index)} cy={y(value)} r="5" fill="var(--surface)" stroke={metric.color} strokeWidth="3" tabIndex={0} role="button" aria-label={`${metric.label}，第 ${index + 1} 次，${metric.format(value)}`} onClick={() => onSelectRun?.(run)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelectRun?.(run) } }}><title>{metric.label} · 第 {index + 1} 次 · {metric.format(value)}</title></circle> })}</g>
        })}
        {points.map((run, index) => <text key={`x-${run.id ?? index}`} x={x(index)} y={height - 11} textAnchor="middle" className="chart-axis-label">第 {index + 1} 次</text>)}
      </svg><div className="evaluation-chart-legend">{definition.metrics.map((metric) => <span key={metric.key}><i style={{ background: metric.color }} />{metric.label}</span>)}<span className="chart-hint"><ArrowUpRight size={13} />点击圆点看这一轮</span></div></div>}
    </article>
  )
}

function valueOf(kind: string): (run: EvaluationRunWire) => number | undefined {
  return (run) => {
    const values: Record<string, unknown> = {
      successRate: run.successRate ?? run.success_rate,
      duration: run.durationMs ?? run.duration_ms,
      agentLatency: run.agentLatencyMs ?? run.agent_latency_ms,
      firstVisibleLatency: run.firstVisibleLatencyMs ?? run.first_visible_latency_ms,
      tokens: run.totalTokens ?? run.total_tokens,
      cost: run.cost,
    }
    if (typeof values[kind] !== 'number' || !Number.isFinite(values[kind])) return undefined
    const number = values[kind] as number
    return kind === 'successRate' && number > 1 ? number / 100 : number
  }
}

function scoreOf(key: string): (run: EvaluationRunWire) => number | undefined {
  return (run) => {
    const value = run.scores?.[key]?.score
    if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
    return value > 1 ? value / 100 : value
  }
}

function formatAxisTick(id: string, value: number): string {
  if (id === 'quality') return `${Math.round(value * 100)}%`
  if (id === 'tokens') return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : Math.round(value).toLocaleString('zh-CN')
  if (id === 'cost') return value < 1 ? value.toFixed(4) : value.toFixed(2)
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value)}ms`
}
