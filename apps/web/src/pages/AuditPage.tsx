import { AlertTriangle, CheckCircle2, Database, RefreshCw, ShieldCheck } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { AuditEventList } from '../features/observability/components/AuditEventList'
import { AuditOverview } from '../features/observability/components/AuditOverview'
import { TraceList } from '../features/observability/components/TraceList'
import { TraceReplay } from '../features/observability/components/TraceReplay'
import { eventStatus, groupTraces } from '../features/observability/presentation'
import { useObservabilityEvents } from '../features/observability/model'
import type { AuditFilter } from '../features/observability/types'
import { PageHeader } from '../shared/components/PageHeader'
import { MetricTile } from '../shared/components/MetricTile'

const filters: Array<{ key: AuditFilter; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'errors', label: '异常' },
  { key: 'rag', label: 'RAG' },
  { key: 'provider', label: 'Provider' },
]

export function AuditPage() {
  const telemetry = useObservabilityEvents(300)
  const [filter, setFilter] = useState<AuditFilter>('all')
  const [selectedTraceId, setSelectedTraceId] = useState<string>()
  const traces = useMemo(() => groupTraces(telemetry.events), [telemetry.events])
  const selectedTrace = traces.find((trace) => trace.id === selectedTraceId) ?? traces[0]
  const metrics = useMemo(() => {
    const errors = telemetry.events.filter((event) => eventStatus(event) === 'error').length
    const rag = telemetry.events.filter((event) => `${event.name ?? ''} ${event.event_type ?? ''}`.toLowerCase().includes('rag')).length
    const providers = telemetry.events.filter((event) => `${event.name ?? ''} ${event.event_type ?? ''}`.toLowerCase().includes('provider')).length
    return { errors, rag, providers }
  }, [telemetry.events])

  useEffect(() => {
    if (traces.length && !traces.some((trace) => trace.id === selectedTraceId)) setSelectedTraceId(traces[0].id)
  }, [traces, selectedTraceId])
  return (
    <div className="page-stack">
      <PageHeader eyebrow="AUDIT" title="审计中心" description="查看近期运行事件与异常信号，帮助定位链路问题。" actions={<button className="icon-button" type="button" onClick={() => void telemetry.refresh()} disabled={telemetry.isRefreshing} aria-label="刷新审计事件" title="刷新审计事件"><RefreshCw size={16} className={telemetry.isRefreshing ? 'spin' : undefined} /></button>} />
      <div className="metric-grid metric-grid--three"><MetricTile label="正常事件" value={telemetry.events.length - metrics.errors} detail="最近缓冲" icon={<CheckCircle2 size={15} />} tone="accent" /><MetricTile label="异常事件" value={metrics.errors} detail="需要关注" icon={<AlertTriangle size={15} />} tone={metrics.errors ? 'danger' : 'neutral'} /><MetricTile label="RAG / Provider" value={`${metrics.rag} / ${metrics.providers}`} detail="按类型统计" icon={<Database size={15} />} tone="neutral" /></div>
      {telemetry.error && <div className="page-alert" role="alert">{telemetry.error}</div>}
      <AuditOverview events={telemetry.events} />
      <div className="audit-trace-grid">
        <section className="work-panel trace-list-panel" aria-labelledby="audit-traces-title">
          <div className="section-heading">
            <div><p className="eyebrow">TRACE</p><h2 id="audit-traces-title">链路回放</h2></div>
            <span className="panel-count">{traces.length}</span>
          </div>
          <TraceList groups={traces} selectedId={selectedTrace?.id} onSelect={setSelectedTraceId} />
        </section>
        <TraceReplay group={selectedTrace} />
      </div>
      <section className="work-panel audit-panel" aria-labelledby="audit-events-title"><div className="section-heading"><div><p className="eyebrow">EVENT LOG</p><h2 id="audit-events-title">事件记录</h2></div><ShieldCheck size={17} /></div><div className="filter-tabs" role="tablist" aria-label="审计事件筛选">{filters.map((item) => <button key={item.key} className={filter === item.key ? 'filter-tab filter-tab--active' : 'filter-tab'} type="button" onClick={() => setFilter(item.key)} role="tab" aria-selected={filter === item.key}>{item.label}</button>)}</div><AuditEventList events={telemetry.events} filter={filter} /></section>
    </div>
  )
}
