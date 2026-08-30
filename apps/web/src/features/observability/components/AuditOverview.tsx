import { Activity, Database, Radio, ShieldCheck } from 'lucide-react'
import type { TelemetryEvent } from '../types'

interface AuditOverviewProps {
  events: TelemetryEvent[]
}

const groups: Array<{ label: string; match: (value: string) => boolean; icon: typeof Activity; tone: string }> = [
  { label: '会话与 Agent', match: (value) => value.includes('chat') || value.includes('agent') || value.includes('run'), icon: Activity, tone: 'blue' },
  { label: 'RAG 检索', match: (value) => value.includes('rag') || value.includes('retriev'), icon: Database, tone: 'green' },
  { label: '数字人 Provider', match: (value) => value.includes('provider') || value.includes('avatar'), icon: Radio, tone: 'violet' },
  { label: '安全与策略', match: (value) => value.includes('security') || value.includes('inject'), icon: ShieldCheck, tone: 'orange' },
]

export function AuditOverview({ events }: AuditOverviewProps) {
  const values = groups.map((group) => events.filter((event) => {
    const name = (String(event.name ?? '') + ' ' + String(event.event_type ?? '')).toLowerCase()
    return group.match(name)
  }).length)
  const max = Math.max(1, ...values)
  return (
    <section className="audit-overview" aria-labelledby="audit-overview-title">
      <div className="audit-overview-head"><div><p className="panel-kicker">EVENT MIX</p><h2 id="audit-overview-title">事件类型分布</h2></div><span>{events.length ? '最近缓冲区' : '等待事件'}</span></div>
      <div className="audit-bars">
        {groups.map(({ label, icon: Icon, tone }, index) => <div className="audit-bar-row" key={label}><div className="audit-bar-label"><span className={'audit-bar-icon audit-bar-icon--' + tone}><Icon size={13} /></span><span>{label}</span><strong>{values[index]}</strong></div><div className="audit-bar-track"><i className={'audit-bar-fill audit-bar-fill--' + tone} style={{ width: String((values[index] / max) * 100) + '%' }} /></div></div>)}
      </div>
    </section>
  )
}
