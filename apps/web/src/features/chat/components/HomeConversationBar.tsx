import { AudioLines, Mic, Send, Square } from 'lucide-react'
import { useEffect, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent } from 'react'
import type { AvatarSession } from '../../../shared/api/types'
import type { RealtimeController } from '../../realtime/model'
import { browserSpeechSupported, createBrowserSpeechRecognition, readBrowserSpeechResults, type BrowserSpeechRecognition } from '../../realtime/browserSpeech'

interface HomeConversationBarProps {
  session: AvatarSession | null
  realtime: RealtimeController
  isSending: boolean
  isCreating?: boolean
  onSend: (message: string) => void
  onCreateSession: (initialMessage?: string) => void
}

export function HomeConversationBar({ session, realtime, isSending, isCreating = false, onSend, onCreateSession }: HomeConversationBarProps) {
  const [draft, setDraft] = useState('')
  const [browserVoiceActive, setBrowserVoiceActive] = useState(false)
  const [browserVoiceLevel, setBrowserVoiceLevel] = useState(0)
  const browserRecognitionRef = useRef<BrowserSpeechRecognition | null>(null)
  const browserVoiceStoppingRef = useRef(false)
  const browserRestartTimerRef = useRef<number | null>(null)
  const sessionRef = useRef(session)
  const isCreatingRef = useRef(isCreating)
  const onSendRef = useRef(onSend)
  const onCreateSessionRef = useRef(onCreateSession)
  const recording = realtime.state.recording === 'recording' || realtime.state.recording === 'requesting'
  // 文本 SSE 与实时语音 WebSocket 是两条独立链路。文本不应等待语音通道。
  const ready = Boolean(session) && realtime.state.connection === 'connected'
  const browserVoiceAvailable = browserSpeechSupported()
  const voiceAvailable = (ready && realtime.state.audioSupported) || browserVoiceAvailable

  useEffect(() => {
    sessionRef.current = session
    isCreatingRef.current = isCreating
    onSendRef.current = onSend
    onCreateSessionRef.current = onCreateSession
  }, [isCreating, onCreateSession, onSend, session])

  useEffect(() => () => {
    browserVoiceStoppingRef.current = true
    if (browserRestartTimerRef.current !== null) window.clearTimeout(browserRestartTimerRef.current)
    browserRecognitionRef.current?.abort()
    browserRecognitionRef.current = null
  }, [])

  useEffect(() => {
    if (!browserVoiceActive || typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
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
  }, [browserVoiceActive])

  function submit(event: FormEvent) {
    event.preventDefault()
    const message = draft.trim()
    if (!message) return
    if (!session) {
      if (isCreating) return
      onCreateSession(message)
    } else {
      onSend(message)
    }
    setDraft('')
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.nativeEvent.isComposing || event.keyCode === 229) return
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  async function toggleVoice() {
    if (ready && realtime.state.audioSupported) {
      await realtime.toggleRecording()
      return
    }
    if (!browserVoiceAvailable) {
      return
    }
    if (browserVoiceActive) {
      browserVoiceStoppingRef.current = true
      if (browserRestartTimerRef.current !== null) window.clearTimeout(browserRestartTimerRef.current)
      browserRecognitionRef.current?.stop()
      return
    }
    const recognition = createBrowserSpeechRecognition()
    if (!recognition) return
    browserRecognitionRef.current = recognition
    browserVoiceStoppingRef.current = false
    setBrowserVoiceActive(true)
    recognition.onresult = (event) => {
      const results = readBrowserSpeechResults(event)
      const interim = results.filter((item) => !item.isFinal).map((item) => item.transcript).join(' ')
      if (interim) setDraft(interim)
      const finalText = results.filter((item) => item.isFinal).map((item) => item.transcript).join(' ').trim()
      if (!finalText) return
      setDraft('')
      if (!sessionRef.current) {
        if (isCreatingRef.current) setDraft(finalText)
        else {
          isCreatingRef.current = true
          onCreateSessionRef.current(finalText)
        }
      } else {
        onSendRef.current(finalText)
      }
    }
    recognition.onerror = (event) => {
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        browserVoiceStoppingRef.current = true
        setBrowserVoiceActive(false)
        browserRecognitionRef.current = null
      }
    }
    recognition.onend = () => {
      if (browserRecognitionRef.current !== recognition) return
      if (!browserVoiceStoppingRef.current) {
        browserRestartTimerRef.current = window.setTimeout(() => {
          browserRestartTimerRef.current = null
          try { recognition.start() } catch { setBrowserVoiceActive(false) }
        }, 120)
        return
      }
      setBrowserVoiceActive(false)
      browserRecognitionRef.current = null
    }
    try {
      recognition.start()
    } catch {
      browserVoiceStoppingRef.current = true
      setBrowserVoiceActive(false)
      browserRecognitionRef.current = null
    }
  }

  const placeholder = !session
    ? isCreating ? '正在创建数字人会话…' : '等待数字人连接…'
    : browserVoiceActive ? '实时对话已开启，可随时改口…'
    : realtime.state.connection !== 'connected'
      ? '输入消息，实时通道连接中…'
      : '输入消息，或点击左侧开始说话…'

  return (
    <form className="home-conversation-bar" onSubmit={submit} aria-label="数字人对话输入">
      <button
        className={'home-voice-button' + (recording || browserVoiceActive ? ' home-voice-button--active' : '')}
        style={{ '--voice-level': String(Math.max(0, Math.min(1, recording ? realtime.state.audioLevel : browserVoiceLevel))) } as CSSProperties}
        type="button"
        onClick={() => void toggleVoice()}
        disabled={!voiceAvailable}
        aria-label={recording || browserVoiceActive ? '结束实时对话' : '开始实时对话'}
        title={recording || browserVoiceActive ? '结束实时对话' : browserVoiceAvailable && !(ready && realtime.state.audioSupported) ? '开始实时对话' : '开始实时对话'}
      >
        {recording || browserVoiceActive ? <Square size={19} /> : voiceAvailable ? <Mic size={21} /> : <AudioLines size={21} />}
      </button>
      <textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        maxLength={4000}
        rows={1}
        aria-label="输入消息"
      />
      <button
        className="home-send-button"
        type="submit"
        disabled={!draft.trim() || (!session && isCreating)}
        aria-label={isSending ? '发送新消息并切换当前回应' : '发送消息'}
        title={isSending ? '发送新消息并切换当前回应' : '发送消息'}
      >
        <Send size={20} />
      </button>
    </form>
  )
}
