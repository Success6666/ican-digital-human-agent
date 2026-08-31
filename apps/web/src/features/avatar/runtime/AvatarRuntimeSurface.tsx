import { AlertCircle, LoaderCircle, RefreshCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { AvatarPerformanceCue, AvatarSession } from '../../../shared/api/types'
import type { AvatarRuntimeStatus, BrowserAvatarRuntime } from './browserRuntime'
import { MofaBrowserRuntime } from './mofaRuntime'
import { saveAvatarPreview } from './previewCache'

interface AvatarRuntimeSurfaceProps {
  session: AvatarSession
  speech?: { id: string; text: string; presentation?: AvatarPerformanceCue }
  interruptKey?: string
}

export function AvatarRuntimeSurface({ session, speech, interruptKey }: AvatarRuntimeSurfaceProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const runtimeRef = useRef<BrowserAvatarRuntime>()
  const spokenRef = useRef<string>()
  const [generation, setGeneration] = useState(0)
  const [status, setStatus] = useState<AvatarRuntimeStatus>({ phase: 'loading', progress: 0 })

  useEffect(() => {
    const host = hostRef.current
    const params = session.clientParams
    if (!host || session.provider !== 'mofa' || params?.runtime !== 'mofa-web-sdk') {
      setStatus({ phase: 'error', message: '当前会话未提供可视化数字人 Runtime' })
      return
    }
    let active = true
    const runtime = new MofaBrowserRuntime()
    runtimeRef.current = runtime
    spokenRef.current = undefined
    setStatus({ phase: 'loading', progress: 0, message: '正在连接数字人' })
    void runtime.connect(host, params, (next) => {
      if (!active) return
      setStatus(next)
      if (next.phase === 'ready') window.setTimeout(() => { if (active) saveAvatarPreview(host, session.provider) }, 3_000)
    }).catch(() => {
      if (active) setStatus({ phase: 'error', message: '魔珐数字人连接失败，请检查网络和应用配置' })
    })
    return () => {
      active = false
      if (runtimeRef.current === runtime) runtimeRef.current = undefined
      void runtime.dispose()
      host.replaceChildren()
    }
  }, [generation, session.sessionId])

  useEffect(() => {
    if (!interruptKey) return
    void runtimeRef.current?.interrupt()
  }, [interruptKey])

  useEffect(() => {
    if (status.phase !== 'ready' || !speech || spokenRef.current === speech.id) return
    spokenRef.current = speech.id
    void runtimeRef.current?.speak(speech.text, speech.presentation).catch(() => {
      setStatus({ phase: 'error', message: '数字人播报失败，请重新连接' })
    })
  }, [speech?.id, status.phase])

  return (
    <div className="avatar-runtime-shell">
      <div ref={hostRef} className="avatar-runtime-host" aria-label="数字人展示画面" />
      {status.phase !== 'ready' && status.phase !== 'speaking' && (
        <div className="avatar-runtime-overlay" role="status">
          {status.phase === 'loading' ? <LoaderCircle size={22} className="avatar-waiting-spinner" /> : <AlertCircle size={22} />}
          <strong>{status.message ?? '正在连接数字人'}</strong>
          {status.phase === 'loading' && <span>{status.progress ?? 0}%</span>}
          {status.phase === 'error' && <button className="avatar-stage-cta" type="button" onClick={() => setGeneration((value) => value + 1)}><RefreshCw size={14} />重新连接</button>}
        </div>
      )}
    </div>
  )
}
