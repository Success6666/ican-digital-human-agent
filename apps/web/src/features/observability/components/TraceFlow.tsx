import { Check, CircleAlert, Clock3 } from 'lucide-react'
import type { TraceGroup } from '../types'
import { eventLabel, eventStatus } from '../presentation'

export function TraceFlow({ group }: { group: TraceGroup }) {
  return (
    <div className="trace-flow" aria-label="运行链路流程图">
      {group.events.map((event, index) => {
        const status = eventStatus(event)
        const Icon = status === 'error' ? CircleAlert : status === 'ok' ? Check : Clock3
        return (
          <div className="trace-flow-step" key={event.event_id ?? `${event.name}-${index}`}>
            <span className={`trace-flow-node trace-flow-node--${status}`}><Icon size={13} /></span>
            <span className="trace-flow-label">{eventLabel(event)}</span>
            {index < group.events.length - 1 && <i className="trace-flow-link" aria-hidden="true" />}
          </div>
        )
      })}
    </div>
  )
}
