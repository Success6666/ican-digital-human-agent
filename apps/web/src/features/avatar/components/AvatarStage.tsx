import { AudioWaveform, LoaderCircle } from 'lucide-react'
import type { AvatarSession } from '../../../shared/api/types'
import type { RealtimeState } from '../../realtime/types'

interface AvatarStageProps {
  session: AvatarSession | null
  realtime: RealtimeState
  onCreate: () => void
}

export function AvatarStage({ session, realtime, onCreate }: AvatarStageProps) {
  const connected = Boolean(session && realtime.connection === 'connected')
  const connecting = Boolean(session && (realtime.connection === 'connecting' || realtime.connection === 'reconnecting'))

  return (
    <section className={'avatar-stage' + (connected ? ' avatar-stage--connected' : '')} aria-label="数字人展示区">
      {connected ? (
        <div className="avatar-runtime-host" data-avatar-runtime-host={session?.provider} aria-label="数字人展示画面" />
      ) : (
        <div className="avatar-waiting" role="status">
          {connecting ? <LoaderCircle size={22} className="avatar-waiting-spinner" /> : <AudioWaveform size={22} />}
          <strong>{connecting ? '正在连接数字人' : '等待数字人连接'}</strong>
          {!session && <button className="avatar-stage-cta" type="button" onClick={onCreate}><AudioWaveform size={14} />建立会话</button>}
        </div>
      )}
    </section>
  )
}
