import { Gauge, ShieldCheck, Timer, Wrench } from 'lucide-react'
import type { EvaluationOverview } from '../types'

interface QualitySnapshotProps {
  overview: EvaluationOverview | null
}

const dimensions: Array<{ key: keyof EvaluationOverview; label: string; icon: typeof Gauge; tone: string }> = [
  { key: 'taskSuccessRate', label: '任务成功率', icon: Gauge, tone: 'blue' },
  { key: 'toolCallAccuracy', label: '工具调用准确率', icon: Wrench, tone: 'green' },
  { key: 'groundedness', label: '事实有据性', icon: ShieldCheck, tone: 'violet' },
]

function percent(value: number | undefined): string {
  return value === undefined ? '—' : String(Math.round(value * 100)) + '%'
}

function width(value: number | undefined): string {
  return value === undefined ? '0%' : String(Math.max(0, Math.min(100, value * 100))) + '%'
}

export function QualitySnapshot({ overview }: QualitySnapshotProps) {
  return (
    <section className="quality-snapshot" aria-labelledby="quality-snapshot-title">
      <div className="quality-snapshot-head">
        <div><p className="panel-kicker">QUALITY SIGNALS</p><h2 id="quality-snapshot-title">质量与延迟概览</h2></div>
        <span>来自最近一次可用评测</span>
      </div>
      <div className="quality-snapshot-grid">
        <div className="quality-bars">
          {dimensions.map(({ key, label, icon: Icon, tone }) => {
            const value = overview?.[key] as number | undefined
            return <div className="quality-bar-row" key={String(key)}><div className="quality-bar-label"><span className={'quality-icon quality-icon--' + tone}><Icon size={13} /></span><span>{label}</span><strong>{percent(value)}</strong></div><div className="quality-track"><i className={'quality-fill quality-fill--' + tone} style={{ width: width(value) }} /></div></div>
          })}
        </div>
        <div className="latency-rail" aria-label="Agent 与数字人延迟分段">
          <div className="latency-rail-head"><span><Timer size={13} />响应路径</span><small>p50 / p95</small></div>
          <LatencyRow label="Agent 编排" p50={overview?.agentLatencyP50Ms} p95={overview?.agentLatencyP95Ms} tone="blue" />
          <LatencyRow label="数字人表达" p50={overview?.digitalHumanLatencyP50Ms} p95={overview?.digitalHumanLatencyP95Ms} tone="green" />
          <LatencyRow label="改口生效" p50={overview?.cancellationLatencyP50Ms} p95={overview?.cancellationLatencyP95Ms} tone="orange" />
        </div>
      </div>
    </section>
  )
}

function LatencyRow({ label, p50, p95, tone }: { label: string; p50?: number; p95?: number; tone: string }) {
  const p50Width = p50 === undefined ? 0 : Math.min(100, Math.max(8, p50 / 10))
  const p95Width = p95 === undefined ? 0 : Math.min(100, Math.max(p50Width + 8, p95 / 10))
  return <div className="latency-row"><div><span>{label}</span><small>{p50 === undefined ? '—' : Math.round(p50) + ' ms'} / {p95 === undefined ? '—' : Math.round(p95) + ' ms'}</small></div><div className="latency-track"><i className={'latency-p95 latency-p95--' + tone} style={{ width: String(p95Width) + '%' }} /><i className="latency-p50" style={{ width: String(p50Width) + '%' }} /></div></div>
}
