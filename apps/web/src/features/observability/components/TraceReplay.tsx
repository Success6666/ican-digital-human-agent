import { Check, ChevronLeft, ChevronRight, CircleAlert, Pause, Play, RotateCcw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type { TraceGroup } from '../types'
import { eventLabel, eventStatus, eventTypeLabel, formatDuration, safeAttributes, safeErrorMessage, statusLabel } from '../presentation'
import { formatTime } from '../../../shared/lib/format'

interface TraceReplayProps {
  group?: TraceGroup
}

export function TraceReplay({ group }: TraceReplayProps) {
  const [step, setStep] = useState(0)
  const [playing, setPlaying] = useState(false)

  useEffect(() => {
    setStep(0)
    setPlaying(false)
  }, [group?.id])

  useEffect(() => {
    if (!playing || !group || group.events.length < 2) return
    const timer = window.setInterval(() => {
      setStep((current) => {
        if (current >= group.events.length - 1) {
          setPlaying(false)
          return current
        }
        return current + 1
      })
    }, 850)
    return () => window.clearInterval(timer)
  }, [group, playing])

  const current = group?.events[step]
  const progress = group && group.events.length ? ((step + 1) / group.events.length) * 100 : 0
  const attributes = useMemo(() => current ? safeAttributes(current) : [], [current])

  if (!group || !current) return <div className="replay-empty"><Play size={18} /><span>选择一条运行记录查看回放</span></div>

  return (
    <section className="replay-panel" aria-labelledby="replay-title">
      <div className="replay-head">
        <div><p className="eyebrow">TRACE REPLAY</p><h2 id="replay-title">{group.label}</h2></div>
        <span className={`replay-status replay-status--${group.status}`}>{statusLabel(group.status)}</span>
      </div>
      <div className="replay-progress"><span style={{ width: `${progress}%` }} /></div>
      <div className="replay-step-head"><span>事件 {step + 1} / {group.events.length}</span><span>{formatTime(current.timestamp ?? '')}</span></div>
      <div className="replay-latency-grid" aria-label="实时延迟摘要">
        <div><span>首事件</span><strong>{formatDuration(group.firstEventLatencyMs)}</strong></div>
        <div><span>首可见</span><strong>{formatDuration(group.firstVisibleLatencyMs)}</strong></div>
        <div><span>Agent</span><strong>{formatDuration(group.agentLatencyMs)}</strong></div>
        <div><span>数字人</span><strong>{formatDuration(group.digitalHumanLatencyMs)}</strong></div>
        <div><span>取消</span><strong>{formatDuration(group.cancellationLatencyMs)}</strong></div>
      </div>
      <div className="replay-event">
        <div className="replay-event-title"><span className={`replay-event-icon replay-event-icon--${eventStatus(current)}`}>{eventStatus(current) === 'error' ? <CircleAlert size={16} /> : eventStatus(current) === 'ok' ? <Check size={16} /> : <Play size={15} />}</span><div><strong>{eventLabel(current)}</strong><small>{eventTypeLabel(current.event_type)} · {formatDuration(current.duration_ms)}</small></div></div>
        {attributes.length > 0 && <dl className="replay-attributes">{attributes.map((attribute) => { const [label, value] = attribute.split('：'); return <div key={attribute}><dt>{label}</dt><dd>{value}</dd></div> })}</dl>}
        {safeErrorMessage(current.error_message) && <p className="replay-error">{safeErrorMessage(current.error_message)}</p>}
      </div>
      <div className="replay-controls">
        <button className="icon-button" type="button" onClick={() => { setStep(0); setPlaying(false) }} aria-label="重置回放" title="重置回放"><RotateCcw size={15} /></button>
        <button className="secondary-button replay-play" type="button" onClick={() => setPlaying((value) => !value)} disabled={group.events.length < 2}>{playing ? <Pause size={15} /> : <Play size={15} />}{playing ? '暂停' : '播放'}</button>
        <button className="icon-button" type="button" onClick={() => setStep((value) => Math.max(0, value - 1))} disabled={step === 0} aria-label="上一个事件" title="上一个事件"><ChevronLeft size={16} /></button>
        <button className="icon-button" type="button" onClick={() => setStep((value) => Math.min(group.events.length - 1, value + 1))} disabled={step >= group.events.length - 1} aria-label="下一个事件" title="下一个事件"><ChevronRight size={16} /></button>
      </div>
    </section>
  )
}
