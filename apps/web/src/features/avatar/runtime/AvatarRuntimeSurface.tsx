import { AlertCircle, LoaderCircle, RefreshCw } from 'lucide-react'
import { memo, useEffect, useRef, useState } from 'react'
import type { AvatarPerformanceCue, AvatarSession } from '../../../shared/api/types'
import type { AvatarRuntimeStatus, BrowserAvatarRuntime } from './browserRuntime'
import { MofaBrowserRuntime } from './mofaRuntime'
import { saveAvatarPreview } from './previewCache'

interface AvatarRuntimeSurfaceProps {
  session: AvatarSession
  speech?: { id: string; text: string; presentation?: AvatarPerformanceCue; pending?: boolean }
  interruptKey?: string
  visible?: boolean
  onSpeakingChange?: (speaking: boolean) => void
  onReadyChange?: (ready: boolean) => void
}

export const AvatarRuntimeSurface = memo(function AvatarRuntimeSurface({ session, speech, interruptKey, visible = true, onSpeakingChange, onReadyChange }: AvatarRuntimeSurfaceProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const runtimeRef = useRef<BrowserAvatarRuntime>()
  const spokenMessageRef = useRef<string>()
  const spokenTextRef = useRef('')
  const [generation, setGeneration] = useState(0)
  const [status, setStatus] = useState<AvatarRuntimeStatus>({ phase: 'loading', progress: 0 })

  useEffect(() => {
    runtimeRef.current?.setVisibility(visible)
  }, [visible])

  useEffect(() => {
    const host = hostRef.current
    const params = session.clientParams
    if (!host || session.provider !== 'mofa' || params?.runtime !== 'mofa-web-sdk') {
      setStatus({ phase: 'error', message: '当前会话未提供可视化数字人 Runtime' })
      onReadyChange?.(false)
      return
    }
    let active = true
    const runtime = new MofaBrowserRuntime()
    runtimeRef.current = runtime
    // Reconnecting must not replay the persisted assistant message. Keep the
    // current stream cursor and only send text that arrives after this runtime
    // instance becomes active.
    const currentSpeechMessageId = speech?.id?.split(':', 1)[0]
    spokenMessageRef.current = currentSpeechMessageId
    spokenTextRef.current = speech?.text ?? ''
    setStatus({ phase: 'loading', progress: 0, message: '正在连接数字人' })
    void runtime.connect(host, params, (next) => {
      if (!active) return
      setStatus(next)
      onSpeakingChange?.(next.phase === 'speaking')
      onReadyChange?.(next.phase === 'ready' || next.phase === 'speaking')
      if (next.phase === 'ready') window.setTimeout(() => { if (active) saveAvatarPreview(host, session.provider) }, 3_000)
    }).catch((cause) => {
      void runtime.dispose()
      if (!active) return
      const detail = cause instanceof Error ? cause.message : '未知初始化错误'
      console.error('[Mofa Runtime] connect failed', cause instanceof Error ? cause.name : typeof cause)
      setStatus({ phase: 'error', message: `魔珐数字人连接失败：${detail}` })
      onReadyChange?.(false)
    })
    return () => {
      active = false
      onSpeakingChange?.(false)
      onReadyChange?.(false)
      if (runtimeRef.current === runtime) runtimeRef.current = undefined
      void runtime.dispose()
      host.replaceChildren()
    }
  }, [generation, onReadyChange, onSpeakingChange, session.sessionId])

  useEffect(() => {
    if (!interruptKey) return
    void runtimeRef.current?.interrupt()
  }, [interruptKey])

  useEffect(() => {
    if ((status.phase !== 'ready' && status.phase !== 'speaking') || !speech) return
    const messageId = speech.id.split(':', 1)[0]
    if (spokenMessageRef.current !== messageId) {
      spokenMessageRef.current = messageId
      spokenTextRef.current = ''
    }
    if (!speech.text.startsWith(spokenTextRef.current)) {
      spokenTextRef.current = ''
    }
    const delta = speech.text.slice(spokenTextRef.current.length)
    spokenTextRef.current = speech.text
    if (!delta.trim() && speech.pending) return
    void runtimeRef.current?.speak(delta, speech.presentation, { flush: !speech.pending }).catch(() => {
      setStatus({ phase: 'error', message: '数字人播报失败，请重新连接' })
    })
  }, [speech?.id, speech?.pending, speech?.text, status.phase])

  return (
    <div className="avatar-runtime-shell">
      <div ref={hostRef} className="avatar-runtime-host" aria-label="数字人展示画面" />
      {status.phase !== 'ready' && status.phase !== 'speaking' && (
        <div className={`avatar-runtime-overlay${status.phase === 'warning' ? ' avatar-runtime-overlay--warning' : ''}`} role="status">
          {status.phase === 'loading' ? <LoaderCircle size={22} className="avatar-waiting-spinner" /> : <AlertCircle size={22} />}
          <strong>{status.message ?? '正在连接数字人'}</strong>
          {status.phase === 'loading' && <span>{status.progress ?? 0}%</span>}
          {(status.phase === 'error' || status.phase === 'warning') && <button className="avatar-stage-cta" type="button" onClick={() => setGeneration((value) => value + 1)}><RefreshCw size={14} />重试连接</button>}
        </div>
      )}
    </div>
  )
})
