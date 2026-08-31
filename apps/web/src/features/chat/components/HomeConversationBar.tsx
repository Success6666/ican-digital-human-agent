import { AudioLines, Mic, Send, Square } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
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
  const browserRecognitionRef = useRef<BrowserSpeechRecognition | null>(null)
  const recording = realtime.state.recording === 'recording' || realtime.state.recording === 'requesting'
  // 文本 SSE 与实时语音 WebSocket 是两条独立链路。文本不应等待语音通道。
  const ready = Boolean(session) && realtime.state.connection === 'connected'
  const browserVoiceAvailable = browserSpeechSupported()
  const voiceAvailable = (ready && realtime.state.audioSupported) || browserVoiceAvailable

  useEffect(() => () => {
    browserRecognitionRef.current?.abort()
    browserRecognitionRef.current = null
  }, [])

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
    if (!browserVoiceAvailable) return
    if (browserVoiceActive) {
      browserRecognitionRef.current?.stop()
      return
    }
    const recognition = createBrowserSpeechRecognition()
    if (!recognition) return
    browserRecognitionRef.current = recognition
    setBrowserVoiceActive(true)
    recognition.onresult = (event) => {
      const results = readBrowserSpeechResults(event)
      const interim = results.filter((item) => !item.isFinal).map((item) => item.transcript).join(' ')
      if (interim) setDraft(interim)
      const finalText = results.filter((item) => item.isFinal).map((item) => item.transcript).join(' ').trim()
      if (!finalText) return
      setDraft('')
      if (!session) {
        if (!isCreating) onCreateSession(finalText)
      } else {
        onSend(finalText)
      }
    }
    recognition.onerror = () => setBrowserVoiceActive(false)
    recognition.onend = () => {
      setBrowserVoiceActive(false)
      if (browserRecognitionRef.current === recognition) browserRecognitionRef.current = null
    }
    try {
      recognition.start()
    } catch {
      setBrowserVoiceActive(false)
      browserRecognitionRef.current = null
    }
  }

  const placeholder = !session
    ? isCreating ? '正在创建数字人会话…' : '等待数字人连接…'
    : browserVoiceActive ? '正在聆听，请说话…'
    : realtime.state.connection !== 'connected'
      ? '输入消息，实时通道连接中…'
      : '输入消息，或点击左侧开始说话…'

  return (
    <form className="home-conversation-bar" onSubmit={submit} aria-label="数字人对话输入">
      <button
        className={'home-voice-button' + (recording || browserVoiceActive ? ' home-voice-button--active' : '')}
        type="button"
        onClick={() => void toggleVoice()}
        disabled={!voiceAvailable}
        aria-label={recording || browserVoiceActive ? '结束说话' : '开始说话'}
        title={recording || browserVoiceActive ? '结束说话' : browserVoiceAvailable && !(ready && realtime.state.audioSupported) ? '使用浏览器语音输入' : '开始说话'}
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
