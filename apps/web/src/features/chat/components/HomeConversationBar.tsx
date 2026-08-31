import { AudioLines, Mic, Send, Square } from 'lucide-react'
import { useState, type FormEvent, type KeyboardEvent } from 'react'
import type { AvatarSession } from '../../../shared/api/types'
import type { RealtimeController } from '../../realtime/model'

interface HomeConversationBarProps {
  session: AvatarSession | null
  realtime: RealtimeController
  isSending: boolean
  onSend: (message: string) => void
  onCreateSession: (initialMessage?: string) => void
}

export function HomeConversationBar({ session, realtime, isSending, onSend, onCreateSession }: HomeConversationBarProps) {
  const [draft, setDraft] = useState('')
  const recording = realtime.state.recording === 'recording' || realtime.state.recording === 'requesting'
  const ready = Boolean(session) && realtime.state.connection === 'connected'

  function submit(event: FormEvent) {
    event.preventDefault()
    const message = draft.trim()
    if (!message) return
    if (!session) onCreateSession(message)
    else if (ready) onSend(message)
    else return
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
    if (!ready || !realtime.state.audioSupported) return
    await realtime.toggleRecording()
  }

  const placeholder = !session
    ? '等待数字人连接…'
    : realtime.state.connection !== 'connected'
      ? '正在连接数字人…'
      : '输入消息，或点击左侧开始说话…'

  return (
    <form className="home-conversation-bar" onSubmit={submit} aria-label="数字人对话输入">
      <button
        className={'home-voice-button' + (recording ? ' home-voice-button--active' : '')}
        type="button"
        onClick={() => void toggleVoice()}
        disabled={!ready || !realtime.state.audioSupported}
        aria-label={recording ? '结束说话' : '开始说话'}
        title={recording ? '结束说话' : '开始说话'}
      >
        {recording ? <Square size={19} /> : realtime.state.audioSupported ? <Mic size={21} /> : <AudioLines size={21} />}
      </button>
      <textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={Boolean(session) && !ready}
        maxLength={4000}
        rows={1}
        aria-label="输入消息"
      />
      <button
        className="home-send-button"
        type="submit"
        disabled={!draft.trim() || (Boolean(session) && !ready)}
        aria-label={isSending ? '发送新消息并切换当前回应' : '发送消息'}
        title={isSending ? '发送新消息并切换当前回应' : '发送消息'}
      >
        <Send size={20} />
      </button>
    </form>
  )
}
