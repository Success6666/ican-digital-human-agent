import { BrainCircuit, Check, CircleAlert, CirclePlay, Clock3, Database, ListChecks, PauseCircle, Radio, ShieldCheck, Sparkles, Wrench, X } from 'lucide-react'
import type { TimelineItem } from '../model'
import { formatTime } from '../../../shared/lib/format'

interface EventTimelineProps {
  items: TimelineItem[]
  collapsed?: boolean
  onApproval?: (approvalId: string, approved: boolean) => void
}

const iconByType = {
  start: CirclePlay,
  filler: Sparkles,
  intent: BrainCircuit,
  disclosure: ListChecks,
  security: ShieldCheck,
  rag: Database,
  tool: Wrench,
  provider: Radio,
  performance: Sparkles,
  delta: Clock3,
  done: Check,
  interrupted: PauseCircle,
  error: CircleAlert,
  info: Clock3,
}

export function EventTimeline({ items, collapsed = false, onApproval }: EventTimelineProps) {
  return (
    <section className={`timeline-panel ${collapsed ? 'timeline-panel--collapsed' : ''}`} aria-labelledby="timeline-title">
      <div className="section-heading timeline-heading">
        <div><p className="eyebrow">OBSERVABILITY</p><h2 id="timeline-title">事件时间线</h2></div>
        <span className="event-count">{items.length}</span>
      </div>
      {items.length === 0 ? (
        <div className="timeline-empty"><Clock3 size={21} /><p>发送消息后，这里会显示 Agent、RAG、MCP 和 Provider 的实时事件。</p></div>
      ) : (
        <ol className="timeline-list">
          {items.map((item) => {
            const Icon = iconByType[item.type] ?? Clock3
            return <li key={item.id} className={`timeline-item timeline-item--${item.type}`}>
              <span className="timeline-icon"><Icon size={14} /></span>
              <div className="timeline-copy"><div><strong>{item.title}</strong><time>{formatTime(item.createdAt)}</time></div>{item.detail && <pre>{item.detail}</pre>}{item.approvalId && item.approvalStatus === 'pending' && onApproval && <div className="timeline-approval"><button type="button" onClick={() => onApproval(item.approvalId!, true)}><Check size={13} />批准</button><button type="button" onClick={() => onApproval(item.approvalId!, false)}><X size={13} />拒绝</button></div>}</div>
            </li>
          })}
        </ol>
      )}
    </section>
  )
}
