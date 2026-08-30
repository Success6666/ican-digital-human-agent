import { Activity, RefreshCw } from 'lucide-react'
import { useMemo } from 'react'
import { EvaluationMetrics } from '../features/evaluation/components/EvaluationMetrics'
import { EvaluationTables } from '../features/evaluation/components/EvaluationTables'
import { QualitySnapshot } from '../features/evaluation/components/QualitySnapshot'
import { useEvaluationData } from '../features/evaluation/model'
import { deriveOverview } from '../features/evaluation/presentation'
import { useObservabilityEvents } from '../features/observability/model'
import { PageHeader } from '../shared/components/PageHeader'
import { MetricTile } from '../shared/components/MetricTile'

export function EvaluationPage() {
  const telemetry = useObservabilityEvents(300)
  const evaluation = useEvaluationData()
  const overview = evaluation.overview ?? deriveOverview(evaluation.runs, telemetry.events.length)
  const errorCount = useMemo(
    () => telemetry.events.filter((event) => event.status === 'error' || event.error_message).length,
    [telemetry.events],
  )
  return (
    <div className="page-stack">
      <PageHeader eyebrow="EVALUATION" title="评测中心" description="集中查看质量、安全、成本与分段延迟。" actions={<div className="page-header-actions"><button className="icon-button" type="button" onClick={() => { void telemetry.refresh(); void evaluation.refresh() }} disabled={telemetry.isRefreshing || evaluation.isRefreshing} aria-label="刷新评测数据" title="刷新评测数据"><RefreshCw size={16} className={telemetry.isRefreshing || evaluation.isRefreshing ? 'spin' : undefined} /></button></div>} />
      <div className="evaluation-summary-row"><MetricTile label="评测运行" value={overview?.totalRuns ?? '暂无数据'} detail="数据集评测次数" icon={<Activity size={15} />} tone="accent" /><MetricTile label="遥测事件" value={telemetry.events.length || '暂无数据'} detail="运行链路总量" icon={<Activity size={15} />} tone="neutral" /><MetricTile label="异常事件" value={errorCount || '暂无数据'} detail={errorCount ? '需要关注' : '暂未发现异常'} icon={<Activity size={15} />} tone={errorCount ? 'danger' : 'neutral'} /></div>
      <EvaluationMetrics overview={overview} />
      <QualitySnapshot overview={overview} />
      {(telemetry.error || evaluation.error) && <div className="page-alert" role="alert">{telemetry.error || evaluation.error}</div>}
      {evaluation.unavailable.length > 0 && <div className="page-note" role="status">评测数据接口尚未提供，质量指标会显示为暂无数据。</div>}
      <EvaluationTables datasets={evaluation.datasets} runs={evaluation.runs} />
    </div>
  )
}
