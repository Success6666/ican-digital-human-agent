import { useDeferredValue } from 'react'
import { History, Trash2, X } from 'lucide-react'
import type { ChatMessage } from '../model'
import { MessageBubble } from './MessageBubble'

interface ConversationDrawerProps {
  open: boolean
  messages: ChatMessage[]
  onClose: () => void
  onClear: () => void
}

export function ConversationDrawer({ open, messages, onClose, onClear }: ConversationDrawerProps) {
  const deferredMessages = useDeferredValue(messages)
  if (!open) return null

  return (
    <>
      <button className="conversation-drawer-backdrop" type="button" aria-label="关闭对话记录" onClick={onClose} />
      <aside className="conversation-drawer" aria-label="Agent 对话记录">
        <header className="conversation-drawer-head">
          <div>
            <span className="conversation-drawer-eyebrow"><History size={13} /> CONVERSATION</span>
            <h2>对话记录</h2>
          </div>
          <div className="conversation-drawer-actions">
            <button className="icon-button" type="button" title="清空对话记录" aria-label="清空对话记录" onClick={onClear} disabled={!deferredMessages.length}>
              <Trash2 size={16} />
            </button>
            <button className="icon-button" type="button" title="关闭对话记录" aria-label="关闭对话记录" onClick={onClose}>
              <X size={17} />
            </button>
          </div>
        </header>
        <div className="conversation-drawer-list">
          {deferredMessages.length ? deferredMessages.map((message) => <MessageBubble key={message.id} message={message} />) : (
            <div className="conversation-drawer-empty">暂无对话记录</div>
          )}
        </div>
      </aside>
    </>
  )
}
