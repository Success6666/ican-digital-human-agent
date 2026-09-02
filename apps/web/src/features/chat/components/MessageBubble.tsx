import { memo } from 'react'
import { Bot, UserRound } from 'lucide-react'
import type { ChatMessage } from '../model'
import { formatTime } from '../../../shared/lib/format'

export const MessageBubble = memo(function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user'
  return (
    <article className={`message-row ${isUser ? 'message-row--user' : 'message-row--assistant'}`}>
      <div className="message-avatar" aria-hidden="true">{isUser ? <UserRound size={16} /> : <Bot size={17} />}</div>
      <div className="message-body">
        <div className="message-meta"><strong>{isUser ? '你' : 'Agent'}</strong><time>{formatTime(message.createdAt)}</time>{message.pending && <span className="typing-indicator" aria-label="正在生成"><i /><i /><i /></span>}</div>
        <p className="message-content">{message.content || message.statusText || (message.pending ? '正在思考…' : '')}</p>
      </div>
    </article>
  )
}, (previous, next) => {
  const before = previous.message
  const after = next.message
  return before.id === after.id
    && before.role === after.role
    && before.content === after.content
    && before.statusText === after.statusText
    && before.pending === after.pending
    && before.createdAt === after.createdAt
})
