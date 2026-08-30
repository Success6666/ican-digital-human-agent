import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Eraser, MessageSquareText, Send, Square } from 'lucide-react'
import type { AvatarSession } from '../../../shared/api/types'
import type { ChatMessage, TimelineItem } from '../model'
import { MessageBubble } from './MessageBubble'
import { EventTimeline } from './EventTimeline'

interface ChatPanelProps {
  session: AvatarSession | null
  messages: ChatMessage[]
  timeline: TimelineItem[]
  isSending: boolean
  error: string | null
  onSend: (message: string) => void
  onStop: () => void
  onClear: () => void
}

export function ChatPanel({ session, messages, timeline, isSending, error, onSend, onStop, onClear }: ChatPanelProps) {
  const [draft, setDraft] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)

  useEffect(() => {
    const node = scrollRef.current
    if (node && stickToBottomRef.current) {
      if (typeof node.scrollTo === 'function') {
        node.scrollTo({ top: node.scrollHeight, behavior: 'auto' })
      } else {
        node.scrollTop = node.scrollHeight
      }
    }
  }, [messages])

  function handleMessageScroll() {
    const node = scrollRef.current
    if (!node) return
    const distanceFromBottom = node.scrollHeight - node.scrollTop - node.clientHeight
    stickToBottomRef.current = distanceFromBottom < 48
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!draft.trim() || !session) return
    stickToBottomRef.current = true
    onSend(draft)
    setDraft('')
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  return (
    <section className="chat-panel" aria-labelledby="chat-title">
      <div className="chat-header">
        <div><p className="eyebrow">CONVERSATION</p><h2 id="chat-title">Agent 对话</h2></div>
        <button className="icon-button" type="button" onClick={onClear} disabled={messages.length === 0 && timeline.length === 0} aria-label="清空对话" title="清空对话"><Eraser size={17} /></button>
      </div>
      {!session ? (
        <div className="chat-empty"><div className="empty-icon"><MessageSquareText size={25} /></div><h3>先建立一个数字人会话</h3><p>选择 Provider 后建立会话，消息会通过认证网关进入 Agent。</p></div>
      ) : (
        <>
          <div ref={scrollRef} className="message-list" aria-live="polite" onScroll={handleMessageScroll}>
            {messages.length === 0 && <div className="chat-empty chat-empty--compact"><div className="empty-icon"><MessageSquareText size={22} /></div><h3>会话已就绪</h3><p>试着发送一句问候，观察完整的事件链路。</p></div>}
            {messages.map((message) => <MessageBubble key={message.id} message={message} />)}
          </div>
          {error && <p className="chat-error" role="alert">{error}</p>}
          <form className="composer" onSubmit={submit}>
            <textarea value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={handleKeyDown} placeholder="输入消息" maxLength={4000} disabled={!session} rows={2} />
            <div className="composer-footer"><span>{draft.length}/4000</span>{isSending && <button className="stop-button" type="button" onClick={onStop}><Square size={15} />停止</button>}<button className="send-button" type="submit" disabled={!draft.trim()} title={isSending ? '发送新消息并停止当前响应' : '发送消息'}><Send size={16} />{isSending ? '改口' : '发送'}</button></div>
          </form>
        </>
      )}
      <div className="mobile-timeline"><EventTimeline items={timeline} /></div>
    </section>
  )
}
