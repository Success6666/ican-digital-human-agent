import { CircleAlert, Database, Radio, ShieldCheck } from 'lucide-react'
import type { AuditFilter, TelemetryEvent } from '../types'
import { eventLabel, eventStatus, formatDuration, safeAttributes, statusLabel } from '../presentation'
import { formatTime } from '../../../shared/lib/format'

interface AuditEventListProps {
  events: TelemetryEvent[]
  filter: AuditFilter
}

function matches(event: TelemetryEvent, filter: AuditFilter): boolean {
  if (filter === 'errors') return eventStatus(event) === 'error'
  const name = `${event.name ?? ''} ${event.event_type ?? ''}`.toLowerCase()
  if (filter === 'rag') return name.includes('rag') || name.includes('retriev')
  if (filter === 'provider') return name.includes('provider') || name.includes('avatar')
  return true
}

function iconFor(event: TelemetryEvent) {
  const name = `${event.name ?? ''} ${event.event_type ?? ''}`.toLowerCase()
  if (eventStatus(event) === 'error') return CircleAlert
  if (name.includes('rag') || name.includes('retriev')) return Database
  if (name.includes('provider') || name.includes('avatar')) return Radio
  return ShieldCheck
}

export function AuditEventList({ events, filter }: AuditEventListProps) {
  const visible = events.filter((event) => matches(event, filter))
  if (visible.length === 0) return <div className="data-empty"><ShieldCheck size={18} /><span>当前筛选暂无记录</span></div>
  return (
    <div className="audit-list">
      {visible.map((event, index) => {
        const Icon = iconFor(event)
        const attrs = safeAttributes(event)
        return <article className={`audit-item audit-item--${eventStatus(event)}`} key={event.event_id ?? `${event.timestamp}-${index}`}>
          <span className="audit-icon"><Icon size={15} /></span>
          <div className="audit-copy"><div className="audit-title"><strong>{eventLabel(event)}</strong><span>{statusLabel(eventStatus(event))}</span></div><p>{attrs.join(' · ') || '无附加信息'}</p></div>
          <div className="audit-meta"><time>{formatTime(event.timestamp ?? '')}</time><small>{formatDuration(event.duration_ms)}</small></div>
        </article>
      })}
    </div>
  )
}
