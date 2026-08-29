import { CheckCircle2, CircleAlert, Clock3 } from 'lucide-react'
import type { TraceGroup } from '../types'
import { formatDuration, statusLabel } from '../presentation'
import { formatTime } from '../../../shared/lib/format'

interface TraceListProps {
  groups: TraceGroup[]
  selectedId?: string
  onSelect: (id: string) => void
}

export function TraceList({ groups, selectedId, onSelect }: TraceListProps) {
  if (groups.length === 0) return <div className="data-empty"><Clock3 size={18} /><span>暂无运行记录</span></div>
  return (
    <div className="trace-list" role="listbox" aria-label="运行记录">
      {groups.map((group) => {
        const Icon = group.status === 'error' ? CircleAlert : group.status === 'ok' ? CheckCircle2 : Clock3
        return (
          <button key={group.id} className={`trace-list-item ${selectedId === group.id ? 'trace-list-item--selected' : ''}`} type="button" onClick={() => onSelect(group.id)} role="option" aria-selected={selectedId === group.id}>
            <span className="trace-list-icon"><Icon size={15} /></span>
            <span className="trace-list-copy"><strong>{group.label}</strong><small>{formatTime(group.startedAt ?? '')} · {group.events.length} 个事件</small></span>
            <span className={`trace-list-status trace-list-status--${group.status}`}>{statusLabel(group.status)}<small>{formatDuration(group.durationMs)}</small></span>
          </button>
        )
      })}
    </div>
  )
}
