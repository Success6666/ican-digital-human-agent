import { AlertTriangle, EyeOff } from 'lucide-react'
import type { TraceGroup, TracePhase } from '../types'
import { TRACE_PHASE_HINTS, formatDuration } from '../presentation'

/**
 * End-to-end waterfall for one turn.
 *
 * Each phase is drawn at its real offset from the trace start and sized by its
 * span. Phases the browser never reported render as an explicit gap, because
 * "no data" and "fast" must not look the same when debugging a silent avatar.
 */
export function TraceWaterfall({ group }: { group: TraceGroup }) {
  const observed = group.phases.filter((phase) => phase.observed)
  // Scale against the furthest marker end so a long phase does not clip.
  const total = Math.max(
    group.durationMs,
    ...group.phases.map((phase) => phase.startOffsetMs + (phase.durationMs ?? 0)),
    1,
  )

  return (
    <div className="trace-waterfall" aria-label="全链路阶段瀑布图">
      <div className="trace-waterfall-head">
        <span className={`trace-waterfall-origin trace-waterfall-origin--${group.origin}`}>
          {group.origin === 'browser' ? '端到端（含浏览器）' : '仅服务端'}
        </span>
        <span className="trace-waterfall-caption">
          覆盖 {observed.length} / {group.phases.length} 环节 · 总计 {formatDuration(total)}
        </span>
      </div>
      <ol className="trace-waterfall-rows">
        {group.phases.map((phase) => (
          <PhaseRow key={phase.key} phase={phase} total={total} />
        ))}
      </ol>
    </div>
  )
}

function PhaseRow({ phase, total }: { phase: TracePhase; total: number }) {
  const hint = TRACE_PHASE_HINTS[phase.key]
  if (!phase.observed) {
    return (
      <li className="trace-waterfall-row trace-waterfall-row--missing">
        <span className="trace-waterfall-name">
          <EyeOff size={12} aria-hidden="true" />
          {phase.label}
        </span>
        <span className="trace-waterfall-track">
          <i className="trace-waterfall-gap" title="该环节没有任何事件上报" />
        </span>
        <span className="trace-waterfall-metric">未观测</span>
        <span className="trace-waterfall-detail">{hint}</span>
      </li>
    )
  }

  // A single-marker phase has no span; give it a minimum visible sliver so it
  // is not mistaken for a missing phase.
  const span = phase.durationMs ?? 0
  const left = Math.min(100, (phase.startOffsetMs / total) * 100)
  const width = phase.durationMs === undefined
    ? 0.8
    : Math.max(0.8, Math.min(100 - left, (span / total) * 100))

  return (
    <li className={`trace-waterfall-row trace-waterfall-row--${phase.status}`}>
      <span className="trace-waterfall-name">
        {phase.status === 'error' && <AlertTriangle size={12} aria-hidden="true" />}
        {phase.label}
      </span>
      <span className="trace-waterfall-track">
        <i
          className={`trace-waterfall-bar trace-waterfall-bar--${phase.status}`}
          style={{ left: `${left}%`, width: `${width}%` }}
          title={`起点 +${formatDuration(phase.startOffsetMs)} · 耗时 ${formatDuration(phase.durationMs)}`}
        />
      </span>
      <span className="trace-waterfall-metric">
        {phase.durationMs === undefined ? `+${formatDuration(phase.startOffsetMs)}` : formatDuration(phase.durationMs)}
        <small>{phase.eventCount} 事件</small>
      </span>
      <span className="trace-waterfall-detail">
        {phase.errorMessage ? <em>{phase.errorMessage}</em> : hint}
      </span>
    </li>
  )
}
