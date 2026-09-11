import { AudioLines, Check, Mic, Send, X } from 'lucide-react'
import { useEffect, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent } from 'react'
import type { AvatarSession } from '../../../shared/api/types'
import type { RealtimeController } from '../../realtime/model'
import { browserSpeechSupported, createBrowserSpeechRecognition, readBrowserSpeechResults, type BrowserSpeechRecognition } from '../../realtime/browserSpeech'

interface HomeConversationBarProps {
  session: AvatarSession | null
  realtime: RealtimeController
  isSending: boolean
  isCreating?: boolean
  avatarReady?: boolean
  avatarSpeaking?: boolean
  onSend: (message: string) => void
  pendingApproval?: { id: string; title: string }
  onApproval?: (approvalId: string, approved: boolean) => void
}

export function HomeConversationBar({ session, realtime, isSending, isCreating = false, avatarReady = false, avatarSpeaking = false, onSend, pendingApproval, onApproval }: HomeConversationBarProps) {
  const [draft, setDraft] = useState('')
  const [continuousVoiceActive, setContinuousVoiceActive] = useState(false)
  const [browserVoiceActive, setBrowserVoiceActive] = useState(false)
  const [browserVoiceLevel, setBrowserVoiceLevel] = useState(0)
  const browserRecognitionRef = useRef<BrowserSpeechRecognition | null>(null)
  const browserVoiceStoppingRef = useRef(false)
  const browserVoicePausedRef = useRef(false)
  const browserRecognitionRunningRef = useRef(false)
  const browserRestartTimerRef = useRef<number | null>(null)
  const realtimeRestartTimerRef = useRef<number | null>(null)
  const backendRecordingStartRef = useRef(false)
  const sessionRef = useRef(session)
  const isCreatingRef = useRef(isCreating)
  const onSendRef = useRef(onSend)
  const isSendingRef = useRef(isSending)
  const recording = realtime.state.recording === 'recording' || realtime.state.recording === 'requesting'
  // 文本 SSE 与实时语音 WebSocket 是两条独立链路。文本不应等待语音通道。
  const ready = Boolean(session) && realtime.state.connection === 'connected'
  const browserVoiceAvailable = browserSpeechSupported()
  const backendVoiceAvailable = ready && realtime.state.audioSupported
  const interactionReady = Boolean(session && avatarReady)
  const voiceAvailable = interactionReady && (backendVoiceAvailable || browserVoiceAvailable)

  useEffect(() => {
    sessionRef.current = session
    isCreatingRef.current = isCreating
    onSendRef.current = onSend
    isSendingRef.current = isSending
  }, [isCreating, isSending, onSend, session])

  useEffect(() => () => {
    browserVoiceStoppingRef.current = true
    if (browserRestartTimerRef.current !== null) window.clearTimeout(browserRestartTimerRef.current)
    if (realtimeRestartTimerRef.current !== null) window.clearTimeout(realtimeRestartTimerRef.current)
    browserRecognitionRef.current?.abort()
    browserRecognitionRef.current = null
  }, [])

  useEffect(() => {
    if (!continuousVoiceActive || !backendVoiceAvailable || recording || backendRecordingStartRef.current) return
    if (avatarSpeaking || realtime.state.phase !== 'idle' || realtime.state.playback === 'playing' || realtime.state.runId) return
    realtimeRestartTimerRef.current = window.setTimeout(() => {
      realtimeRestartTimerRef.current = null
      void realtime.startRecording().then((started) => {
        if (!started) setContinuousVoiceActive(false)
      })
    }, 180)
    return () => {
      if (realtimeRestartTimerRef.current !== null) window.clearTimeout(realtimeRestartTimerRef.current)
      realtimeRestartTimerRef.current = null
    }
  }, [avatarSpeaking, backendVoiceAvailable, continuousVoiceActive, realtime.startRecording, realtime.state.phase, realtime.state.playback, realtime.state.runId, recording])

  useEffect(() => {
    const recognition = browserRecognitionRef.current
    if (!browserVoiceActive || !recognition) return
    if (isSending || isCreating || avatarSpeaking) {
      browserVoicePausedRef.current = true
      if (browserRecognitionRunningRef.current) recognition.stop()
      return
    }
    if (!browserVoicePausedRef.current || browserRecognitionRunningRef.current) return
    browserVoicePausedRef.current = false
    scheduleBrowserRecognition(recognition, 180)
  }, [avatarSpeaking, browserVoiceActive, isCreating, isSending])

  useEffect(() => {
    if (!browserVoiceActive || isSending || isCreating || avatarSpeaking || typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setBrowserVoiceLevel(0)
      return
    }
    let active = true
    let frame = 0
    let stream: MediaStream | undefined
    let context: AudioContext | undefined
    let source: MediaStreamAudioSourceNode | undefined
    let analyser: AnalyserNode | undefined
    void navigator.mediaDevices.getUserMedia({ audio: true, video: false }).then(async (nextStream) => {
      if (!active) {
        nextStream.getTracks().forEach((track) => track.stop())
        return
      }
      stream = nextStream
      const Constructor = window.AudioContext ?? (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
      if (!Constructor) return
      context = new Constructor()
      await context.resume().catch(() => undefined)
      source = context.createMediaStreamSource(nextStream)
      analyser = context.createAnalyser()
      analyser.fftSize = 512
      source.connect(analyser)
      const samples = new Uint8Array(analyser.fftSize)
      const tick = () => {
        if (!active || !analyser) return
        analyser.getByteTimeDomainData(samples)
        let energy = 0
        for (const sample of samples) {
          const centered = (sample - 128) / 128
          energy += centered * centered
        }
        setBrowserVoiceLevel(Math.min(1, Math.sqrt(energy / samples.length) * 4))
        frame = window.requestAnimationFrame(tick)
      }
      tick()
    }).catch(() => undefined)
    return () => {
      active = false
      window.cancelAnimationFrame(frame)
      source?.disconnect()
      stream?.getTracks().forEach((track) => track.stop())
      void context?.close()
      setBrowserVoiceLevel(0)
    }
  }, [avatarSpeaking, browserVoiceActive, isCreating, isSending])

  function submit(event: FormEvent) {
    event.preventDefault()
    const message = draft.trim()
    if (!message || !interactionReady || isCreating) return
    onSend(message)
    setDraft('')
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.nativeEvent.isComposing || event.keyCode === 229) return
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  function scheduleBrowserRecognition(recognition: BrowserSpeechRecognition, delay = 120) {
    if (browserRestartTimerRef.current !== null) window.clearTimeout(browserRestartTimerRef.current)
    browserRestartTimerRef.current = window.setTimeout(() => {
      browserRestartTimerRef.current = null
      if (browserVoiceStoppingRef.current || browserVoicePausedRef.current || browserRecognitionRunningRef.current) return
      try {
        recognition.start()
        browserRecognitionRunningRef.current = true
      } catch {
        setContinuousVoiceActive(false)
        setBrowserVoiceActive(false)
      }
    }, delay)
  }

  async function toggleVoice() {
    if (continuousVoiceActive) {
      setContinuousVoiceActive(false)
      if (backendVoiceAvailable) {
        backendRecordingStartRef.current = false
        await realtime.cancelRecording()
      } else {
        browserVoiceStoppingRef.current = true
        browserVoicePausedRef.current = false
        if (browserRestartTimerRef.current !== null) window.clearTimeout(browserRestartTimerRef.current)
        if (browserRecognitionRunningRef.current) browserRecognitionRef.current?.stop()
        else {
          setBrowserVoiceActive(false)
          browserRecognitionRef.current = null
        }
      }
      return
    }
    if (!interactionReady) return
    setContinuousVoiceActive(true)
    if (backendVoiceAvailable) {
      backendRecordingStartRef.current = true
      try {
        const started = await realtime.startRecording()
        if (!started) setContinuousVoiceActive(false)
      } finally {
        backendRecordingStartRef.current = false
      }
      return
    }
    if (!browserVoiceAvailable) {
      setContinuousVoiceActive(false)
      return
    }
    const recognition = createBrowserSpeechRecognition()
    if (!recognition) {
      setContinuousVoiceActive(false)
      return
    }
    browserRecognitionRef.current = recognition
    browserVoiceStoppingRef.current = false
    browserVoicePausedRef.current = false
    browserRecognitionRunningRef.current = false
    setBrowserVoiceActive(true)
    recognition.onresult = (event) => {
      const results = readBrowserSpeechResults(event)
      const interim = results.filter((item) => !item.isFinal).map((item) => item.transcript).join(' ')
      if (interim) setDraft(interim)
      const finalText = results.filter((item) => item.isFinal).map((item) => item.transcript).join(' ').trim()
      if (!finalText) return
      setDraft('')
      browserVoicePausedRef.current = true
      if (sessionRef.current) {
        // Browser recognition is the local ASR fallback. Prefer the same
        // realtime WebSocket text boundary so the Agent and avatar keep one
        // generation; use SSE only while that socket is still connecting.
        const sent = realtime.sendText(finalText)
        if (!sent) onSendRef.current(finalText)
      }
      if (browserRecognitionRunningRef.current) recognition.stop()
    }
    recognition.onerror = (event) => {
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        browserVoiceStoppingRef.current = true
        setContinuousVoiceActive(false)
        setBrowserVoiceActive(false)
        browserRecognitionRef.current = null
      }
    }
    recognition.onend = () => {
      if (browserRecognitionRef.current !== recognition) return
      browserRecognitionRunningRef.current = false
      if (browserVoicePausedRef.current || isSendingRef.current || isCreatingRef.current) return
      if (!browserVoiceStoppingRef.current) {
        scheduleBrowserRecognition(recognition)
        return
      }
      setContinuousVoiceActive(false)
      setBrowserVoiceActive(false)
      browserRecognitionRef.current = null
    }
    try {
      recognition.start()
      browserRecognitionRunningRef.current = true
    } catch {
      browserVoiceStoppingRef.current = true
      setContinuousVoiceActive(false)
      setBrowserVoiceActive(false)
      browserRecognitionRef.current = null
    }
  }

  const placeholder = !session || !avatarReady
    ? isCreating ? '正在创建数字人会话…' : '等待数字人连接…'
    : continuousVoiceActive
      ? recording || browserVoiceActive && !isSending ? '实时对话中 · 正在聆听…'
        : realtime.state.phase === 'speaking' || isSending ? '实时对话中 · 数字人正在回答…'
          : realtime.state.phase === 'thinking' ? '实时对话中 · 正在理解…'
            : '实时对话中 · 正在准备下一轮…'
    : realtime.state.connection !== 'connected'
      ? '输入消息，实时通道连接中…'
      : '输入消息，或点击左侧进入实时对话…'

  return (
    <form className="home-conversation-bar" onSubmit={submit} aria-label="数字人对话输入">
      {pendingApproval && onApproval && <div className="home-approval" role="status"><span>{pendingApproval.title}</span><button type="button" onClick={() => onApproval(pendingApproval.id, true)} title="批准工具执行" aria-label="批准工具执行"><Check size={15} /></button><button type="button" onClick={() => onApproval(pendingApproval.id, false)} title="拒绝工具执行" aria-label="拒绝工具执行"><X size={15} /></button></div>}
      <button
        className={'home-voice-button' + (continuousVoiceActive ? ' home-voice-button--active' : '')}
        style={{ '--voice-level': String(Math.max(0, Math.min(1, recording ? realtime.state.audioLevel : browserVoiceLevel))) } as CSSProperties}
        type="button"
        onClick={() => void toggleVoice()}
        disabled={!voiceAvailable && !continuousVoiceActive}
        aria-pressed={continuousVoiceActive}
        aria-label={continuousVoiceActive ? '退出实时对话' : '进入实时对话'}
        title={continuousVoiceActive ? '退出实时对话' : '进入实时对话'}
      >
        {continuousVoiceActive ? <AudioLines size={21} /> : voiceAvailable ? <Mic size={21} /> : <AudioLines size={21} />}
      </button>
      <textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        maxLength={4000}
        rows={1}
        aria-label="输入消息"
        disabled={!interactionReady || isCreating}
      />
      <button
        className="home-send-button"
        type="submit"
        disabled={!draft.trim() || !interactionReady || isCreating}
        aria-label={isSending ? '发送新消息并切换当前回应' : '发送消息'}
        title={isSending ? '发送新消息并切换当前回应' : '发送消息'}
      >
        <Send size={20} />
      </button>
    </form>
  )
}
