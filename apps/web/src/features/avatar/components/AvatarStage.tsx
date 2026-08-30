import { AudioWaveform, Bot, ScanFace, ShieldCheck, Sparkles } from 'lucide-react'
import { StatusPill } from '../../../shared/components/StatusPill'
import type { AvatarSession, ProviderStatus } from '../../../shared/api/types'
import type { RealtimeState } from '../../realtime/types'

interface AvatarStageProps {
  provider: ProviderStatus | null
  session: AvatarSession | null
  realtime: RealtimeState
  onCreate: () => void
}

function phaseLabel(state: RealtimeState, session: AvatarSession | null): string {
  if (!session) return '等待建立会话'
  if (state.phase === 'listening') return '正在聆听'
  if (state.phase === 'thinking') return '正在组织回应'
  if (state.phase === 'speaking') return '正在表达'
  if (state.phase === 'interrupting') return '正在切换话题'
  if (state.phase === 'degraded') return '文本模式'
  return '已准备好'
}

function statusFor(state: RealtimeState, session: AvatarSession | null): { status: 'online' | 'pending' | 'idle' | 'active' | 'offline' | 'error'; label: string } {
  if (!session) return { status: 'idle', label: '未连接' }
  if (state.phase === 'error' || state.connection === 'error') return { status: 'error', label: '需要检查' }
  if (state.phase === 'speaking') return { status: 'active', label: '表达中' }
  if (state.connection === 'connecting' || state.connection === 'reconnecting') return { status: 'pending', label: '连接中' }
  return { status: 'online', label: '运行中' }
}

export function AvatarStage({ provider, session, realtime, onCreate }: AvatarStageProps) {
  const runtimeStatus = statusFor(realtime, session)
  const phase = phaseLabel(realtime, session)
  const expression = realtime.phase === 'speaking' ? '专注' : realtime.phase === 'listening' ? '倾听' : '自然'

  return (
    <section className="avatar-stage" aria-labelledby="avatar-stage-title">
      <div className="avatar-stage-head">
        <div className="avatar-stage-title"><Sparkles size={15} /><span id="avatar-stage-title">数字人工作台</span></div>
        <div className="avatar-stage-meta">
          <small>{provider?.label || '未选择 Provider'}</small>
          <StatusPill status={runtimeStatus.status} label={runtimeStatus.label} />
        </div>
      </div>
      <div className="avatar-visual" aria-hidden="true">
        <div className="avatar-figure">
          <div className="avatar-hair" />
          <div className="avatar-head"><span className="avatar-mouth" /></div>
          <div className="avatar-neck" />
          <div className="avatar-body" />
        </div>
      </div>
      <div className="avatar-stage-caption">
        <div className="avatar-stage-status">
          <span className="avatar-stage-status-icon"><Bot size={13} /></span>
          <span><strong>{phase}</strong><small>{session ? 'Fay Runtime · 会话已隔离' : '选择 Provider 后开始'}</small></span>
        </div>
        <div className="avatar-stage-expression"><ScanFace size={13} /><span>微表情：{expression}</span></div>
      </div>
      <div className="avatar-stage-footer">
        <div className="avatar-stage-signal"><ShieldCheck size={13} /><span>认证网关已保护</span></div>
        <div className="avatar-stage-wave" aria-label="表达音频状态"><i /><i /><i /><i /><i /></div>
        {!session && <button className="avatar-stage-cta" type="button" onClick={onCreate}><AudioWaveform size={14} />建立会话</button>}
      </div>
    </section>
  )
}
