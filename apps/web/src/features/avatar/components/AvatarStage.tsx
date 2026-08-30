import { AudioWaveform, LoaderCircle } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { AvatarSession } from '../../../shared/api/types'
import { AvatarRuntimeSurface } from '../runtime/AvatarRuntimeSurface'
import { AvatarPreviewSurface } from '../runtime/AvatarPreviewSurface'
import { readAvatarPreview, subscribeAvatarPreview, type AvatarPreview } from '../runtime/previewCache'

interface AvatarStageProps {
  session: AvatarSession | null
  isCreating: boolean
  speech?: { id: string; text: string }
  interruptKey?: string
  activate?: boolean
  onCreate: () => void
}

export function AvatarStage({ session, isCreating, speech, interruptKey, activate = false, onCreate }: AvatarStageProps) {
  const [preview, setPreview] = useState<AvatarPreview | null>(() => readAvatarPreview())
  const [runtimeActive, setRuntimeActive] = useState(() => !readAvatarPreview())
  const idleTimerRef = useRef<number>()

  const activateRuntime = useCallback(() => {
    setRuntimeActive(true)
    if (idleTimerRef.current) window.clearTimeout(idleTimerRef.current)
    idleTimerRef.current = window.setTimeout(() => setRuntimeActive(false), 30_000)
  }, [])

  useEffect(() => {
    const nextPreview = readAvatarPreview()
    setPreview(nextPreview)
    if (!session) {
      setRuntimeActive(false)
      return
    }
    if (!nextPreview) activateRuntime()
    return subscribeAvatarPreview(() => setPreview(readAvatarPreview()))
  }, [activateRuntime, session?.sessionId])

  useEffect(() => {
    if (activate || speech?.id) activateRuntime()
  }, [activate, activateRuntime, speech?.id])

  useEffect(() => () => {
    if (idleTimerRef.current) window.clearTimeout(idleTimerRef.current)
  }, [])

  const shouldConnect = Boolean(session && runtimeActive)
  return (
    <section className={'avatar-stage' + (session ? ' avatar-stage--connected' : '')} aria-label="数字人展示区">
      {session && shouldConnect ? (
        <AvatarRuntimeSurface session={session} speech={speech} interruptKey={interruptKey} />
      ) : session && preview ? (
        <AvatarPreviewSurface preview={preview} />
      ) : (
        <div className="avatar-waiting" role="status">
          {isCreating ? <LoaderCircle size={22} className="avatar-waiting-spinner" /> : <AudioWaveform size={22} />}
          <strong>{isCreating ? '正在创建数字人会话' : '等待数字人连接'}</strong>
          {!isCreating && <button className="avatar-stage-cta" type="button" onClick={onCreate}><AudioWaveform size={14} />建立会话</button>}
        </div>
      )}
    </section>
  )
}
