import { AlertCircle, LoaderCircle, RefreshCw, VolumeX } from 'lucide-react'
import { memo, useCallback, useEffect, useRef, useState } from 'react'
import type { AvatarPerformanceCue, AvatarSession } from '../../../shared/api/types'
import { reportClientEvent } from '../../observability/clientReporter'
import type { AvatarRuntimeStatus, BrowserAvatarRuntime } from './browserRuntime'
import { avatarAudioState, bindGestureAudioUnlock, installAudioContextTracker, unlockAvatarAudio } from './audioUnlock'
import { MofaBrowserRuntime } from './mofaRuntime'
import { saveAvatarPreview } from './previewCache'

/**
 * Trace handle handed to the avatar runtime.
 *
 * A getter is used instead of a value because the avatar runtime outlives any
 * single run: it connects once per session while traces are created per
 * utterance. Reading lazily keeps speak markers attached to the run that was
 * actually speaking when the SDK answered.
 */
export interface AvatarTraceSource {
  traceId(): string | undefined
  runId(): string | undefined
  utteranceId(): string | undefined
  revision(): number | undefined
}

interface AvatarRuntimeSurfaceProps {
  session: AvatarSession
  speech?: { id: string; text: string; presentation?: AvatarPerformanceCue; pending?: boolean }
  interruptKey?: string
  visible?: boolean
  traceSource?: AvatarTraceSource
  onSpeakingChange?: (speaking: boolean) => void
  onReadyChange?: (ready: boolean) => void
}

export const AvatarRuntimeSurface = memo(function AvatarRuntimeSurface({ session, speech, interruptKey, visible = true, traceSource, onSpeakingChange, onReadyChange }: AvatarRuntimeSurfaceProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const runtimeRef = useRef<BrowserAvatarRuntime>()
  const spokenMessageRef = useRef<string>()
  const spokenTextRef = useRef('')
  const traceSourceRef = useRef(traceSource)
  traceSourceRef.current = traceSource
  const [generation, setGeneration] = useState(0)
  const [status, setStatus] = useState<AvatarRuntimeStatus>({ phase: 'loading', progress: 0 })
  // Phones keep audio suspended until a real gesture. The avatar then speaks
  // with no sound and no visible reason, so the silence gets a way out.
  const [audioBlocked, setAudioBlocked] = useState(false)

  const handleUnlockAudio = useCallback(() => {
    // Runs inside a click, which is the only moment a phone will accept it.
    void unlockAvatarAudio().then((state) => {
      if (state.unlocked) setAudioBlocked(false)
    })
  }, [])

  // A phone only leaves `suspended` when audio is played from inside a real
  // gesture. The avatar connects before the first tap, so the unlock has to be
  // armed on the document rather than waiting for a click on the stage.
  useEffect(() => {
    installAudioContextTracker()
    return bindGestureAudioUnlock()
  }, [])

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
    runtime.setTraceContext?.({
      traceId: () => traceSourceRef.current?.traceId(),
      runId: () => traceSourceRef.current?.runId(),
      utteranceId: () => traceSourceRef.current?.utteranceId(),
      revision: () => traceSourceRef.current?.revision(),
    })
    // Reconnecting must not replay the persisted assistant message. Keep the
    // current stream cursor and only send text that arrives after this runtime
    // instance becomes active.
    const currentSpeechMessageId = speech?.id?.split(':', 1)[0]
    spokenMessageRef.current = currentSpeechMessageId
    spokenTextRef.current = speech?.text ?? ''
    setStatus({ phase: 'loading', progress: 0, message: '正在连接数字人' })
    // Best effort: this is not inside a gesture, so a phone will ignore it and
    // rely on the document-level unlock. On a desktop it warms up the context
    // before the first utterance instead of during it.
    void unlockAvatarAudio()
    void runtime.connect(host, params, (next) => {
      if (!active) return
      setStatus((previous) => {
        if (previous.phase !== next.phase) {
          reportSpeechMarker(traceSourceRef.current, 'avatar.phase_changed', {
            attributes: {
              from: previous.phase,
              to: next.phase,
              progress: next.progress,
              message: next.message,
            },
          })
        }
        return next
      })
      onSpeakingChange?.(next.phase === 'speaking')
      onReadyChange?.(next.phase === 'ready' || next.phase === 'speaking')
      if (next.phase === 'ready') window.setTimeout(() => { if (active) saveAvatarPreview(host, session.provider) }, 3_000)
    }).catch((cause) => {
      void runtime.dispose()
      if (!active) return
      const detail = cause instanceof Error ? cause.message : '未知初始化错误'
      console.error('[Mofa Runtime] connect failed', cause instanceof Error ? cause.name : typeof cause)
      // The runtime reports `avatar.connect_failed` itself; surface the same
      // reason through the status callback so the user-facing chrome and the
      // trace agree on what stopped the avatar.
      reportSpeechMarker(traceSourceRef.current, 'avatar.phase_changed', {
        status: 'error',
        attributes: { from: 'loading', to: 'error', reason: detail },
      })
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
    if ((status.phase !== 'ready' && status.phase !== 'speaking') || !speech) {
      // The server-side trace records deltas, but only the browser knows they
      // were dropped because the runtime was not ready. Record the skip so a
      // silent run can be told apart from a run that never produced text.
      if (speech && status.phase !== 'ready' && status.phase !== 'speaking') {
        reportSpeechMarker(traceSourceRef.current, 'speech.skipped', {
          attributes: { phase: status.phase, textLength: speech.text.length },
        })
      }
      return
    }
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
    reportSpeechMarker(traceSourceRef.current, 'speech.assembled', {
      attributes: {
        deltaLength: delta.length,
        totalLength: speech.text.length,
        flush: !speech.pending,
        hasPresentation: Boolean(speech.presentation),
      },
    })
    void runtimeRef.current?.speak(delta, speech.presentation, { flush: !speech.pending }).catch((cause) => {
      reportSpeechMarker(traceSourceRef.current, 'speech.dispatch_failed', {
        status: 'error',
        attributes: { reason: cause instanceof Error ? cause.message : 'speak_failed' },
      })
      setStatus({ phase: 'error', message: '数字人播报失败，请重新连接' })
    })
    if (!avatarAudioState().unlocked) setAudioBlocked(true)
  }, [speech?.id, speech?.pending, speech?.text, status.phase])

  return (
    <div className="avatar-runtime-shell">
      <div ref={hostRef} className="avatar-runtime-host" aria-label="数字人展示画面" />
      {audioBlocked && (
        <button className="avatar-audio-hint" type="button" onClick={handleUnlockAudio}>
          <VolumeX size={14} aria-hidden="true" />点击开启声音
        </button>
      )}
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

/** Emit a delta -> speech marker when a trace is already known for this run. */
function reportSpeechMarker(
  source: AvatarTraceSource | undefined,
  name: string,
  options: { status?: 'ok' | 'error'; attributes?: Record<string, unknown> } = {},
): void {
  const traceId = source?.traceId()
  if (!traceId) return
  reportClientEvent({
    name,
    traceId,
    runId: source?.runId(),
    utteranceId: source?.utteranceId(),
    revision: source?.revision(),
    status: options.status,
    attributes: options.attributes,
  })
}
