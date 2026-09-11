import { AudioWaveform, LoaderCircle } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import type { AvatarSession } from '../../../shared/api/types'
import { AvatarRuntimeSurface, type AvatarTraceSource } from '../runtime/AvatarRuntimeSurface'
import { AvatarPreviewSurface } from '../runtime/AvatarPreviewSurface'
import { readAvatarPreview, subscribeAvatarPreview, type AvatarPreview } from '../runtime/previewCache'

interface AvatarStageProps {
  session: AvatarSession | null
  isCreating: boolean
  speech?: { id: string; text: string; presentation?: import('../../../shared/api/types').AvatarPerformanceCue; pending?: boolean }
  interruptKey?: string
  activate?: boolean
  visible?: boolean
  traceSource?: AvatarTraceSource
  onSpeakingChange?: (speaking: boolean) => void
  onReadyChange?: (ready: boolean) => void
  onCreate: () => void
  onDisconnect: () => void
}

export function AvatarStage({ session, isCreating, speech, interruptKey, activate = false, visible = true, traceSource, onSpeakingChange, onReadyChange, onCreate, onDisconnect }: AvatarStageProps) {
  const [preview, setPreview] = useState<AvatarPreview | null>(() => readAvatarPreview())
  const [runtimeActive, setRuntimeActive] = useState(() => !readAvatarPreview())
  const activateRuntime = useCallback(() => {
    setRuntimeActive(true)
  }, [])

  useEffect(() => {
    const nextPreview = readAvatarPreview()
    setPreview(nextPreview)
    if (!session) {
      setRuntimeActive(false)
      onReadyChange?.(false)
      return
    }
    activateRuntime()
    return subscribeAvatarPreview(() => setPreview(readAvatarPreview()))
  }, [activateRuntime, onReadyChange, session?.sessionId])

  useEffect(() => {
    if (activate || speech?.id) activateRuntime()
  }, [activate, activateRuntime, speech?.id])

  const shouldConnect = Boolean(session && runtimeActive)
  return (
    <section className={'avatar-stage' + (session ? ' avatar-stage--connected' : '')} aria-label="数字人展示区">
      {session && shouldConnect ? (
        <AvatarRuntimeSurface session={session} speech={speech} interruptKey={interruptKey} visible={visible} traceSource={traceSource} onSpeakingChange={onSpeakingChange} onReadyChange={onReadyChange} />
      ) : preview ? (
        <>
          <AvatarPreviewSurface preview={preview} />
        </>
      ) : (
        <div className="avatar-waiting" role="status">
          {isCreating ? <LoaderCircle size={22} className="avatar-waiting-spinner" /> : <AudioWaveform size={22} />}
          <strong>{isCreating ? '正在创建数字人会话' : '等待数字人连接'}</strong>
          {!isCreating && <button className="avatar-stage-cta" type="button" onClick={onCreate}><AudioWaveform size={14} />连接数字人</button>}
        </div>
      )}
      {(session || preview) && <button className="avatar-stage-connect-button" type="button" onClick={session ? onDisconnect : onCreate} disabled={isCreating}>{isCreating ? '正在连接…' : session ? '断开连接' : '连接数字人'}</button>}
    </section>
  )
}
