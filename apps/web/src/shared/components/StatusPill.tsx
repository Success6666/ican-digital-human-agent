import { CircleCheck, CircleDot, CircleX, LoaderCircle } from 'lucide-react'

type Status = 'online' | 'offline' | 'pending' | 'active' | 'idle' | 'error'

interface StatusPillProps {
  status: Status
  label: string
}

const iconByStatus = {
  online: CircleCheck,
  active: CircleCheck,
  offline: CircleX,
  error: CircleX,
  pending: LoaderCircle,
  idle: CircleDot,
}

export function StatusPill({ status, label }: StatusPillProps) {
  const Icon = iconByStatus[status]
  return <span className={`status-pill status-pill--${status}`}><Icon size={13} aria-hidden="true" />{label}</span>
}
