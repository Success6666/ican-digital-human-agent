import type { ReactNode } from 'react'

interface MetricTileProps {
  label: string
  value: ReactNode
  detail?: string
  icon?: ReactNode
  tone?: 'accent' | 'warning' | 'danger' | 'neutral'
}

export function MetricTile({ label, value, detail, icon, tone = 'neutral' }: MetricTileProps) {
  return (
    <article className={`metric-tile metric-tile--${tone}`}>
      <div className="metric-tile-head"><span>{label}</span>{icon}</div>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </article>
  )
}
