import { memo } from 'react'
import { History, MessageSquareText, Plus, Trash2, X } from 'lucide-react'
import type { ChatConversation, ChatMessage } from '../model'
import { MessageBubble } from './MessageBubble'

interface ConversationDrawerProps {
  open: boolean
  messages: ChatMessage[]
  conversations: ChatConversation[]
  activeConversationId: string | null
  onClose: () => void
  onClear: () => void
  onNew: () => void
  onSelect: (conversationId: string) => void
  onDelete: (conversationId: string) => void
}

function ConversationDrawerView({ open, messages, conversations, activeConversationId, onClose, onClear, onNew, onSelect, onDelete }: ConversationDrawerProps) {
  if (!open) return null

  return (
      <aside className="conversation-drawer" aria-label="Agent 对话记录">
        <header className="conversation-drawer-head">
          <div>
            <span className="conversation-drawer-eyebrow"><History size={13} /> CONVERSATION</span>
            <h2>对话记录</h2>
          </div>
          <div className="conversation-drawer-actions">
            <button className="icon-button" type="button" title="清空对话记录" aria-label="清空对话记录" onClick={onClear} disabled={!messages.length}>
              <Trash2 size={16} />
            </button>
            <button className="icon-button" type="button" title="关闭对话记录" aria-label="关闭对话记录" onClick={onClose}>
              <X size={17} />
            </button>
          </div>
        </header>
        <div className="conversation-history-toolbar">
          <button className="conversation-new-button" type="button" onClick={onNew}><Plus size={15} />新对话</button>
          <span>{conversations.length} 个会话</span>
        </div>
        <nav className="conversation-session-list" aria-label="历史会话">
          {conversations.map((conversation) => (
            <div className={`conversation-session-row${conversation.id === activeConversationId ? ' conversation-session-row--active' : ''}`} key={conversation.id}>
              <button className="conversation-session-select" type="button" onClick={() => onSelect(conversation.id)}>
                <MessageSquareText size={14} />
                <span><strong>{conversation.title}</strong><small>{new Date(conversation.updatedAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</small></span>
              </button>
              <button className="conversation-session-delete" type="button" title="删除该会话" aria-label={`删除会话：${conversation.title}`} onClick={() => onDelete(conversation.id)}><Trash2 size={14} /></button>
            </div>
          ))}
        </nav>
        <div className="conversation-current-label">当前会话内容</div>
        <div className="conversation-drawer-list">
          {messages.length ? messages.map((message) => <MessageBubble key={message.id} message={message} />) : (
            <div className="conversation-drawer-empty">暂无对话记录</div>
          )}
        </div>
      </aside>
  )
}

export const ConversationDrawer = memo(ConversationDrawerView)
