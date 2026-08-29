import { Activity } from 'lucide-react'
import type { useAvatar } from '../features/avatar/model'
import type { useChat } from '../features/chat/model'
import { ProviderPanel } from '../features/avatar/components/ProviderPanel'
import { ChatPanel } from '../features/chat/components/ChatPanel'
import { EventTimeline } from '../features/chat/components/EventTimeline'
import { RuntimeStrip } from '../features/runtime/components/RuntimeStrip'
import { PageHeader } from '../shared/components/PageHeader'

type AvatarState = ReturnType<typeof useAvatar>
type ChatState = ReturnType<typeof useChat>

interface HomePageProps {
  avatar: AvatarState
  chat: ChatState
}

export function HomePage({ avatar, chat }: HomePageProps) {
  return (
    <div className="page-stack home-page">
      <PageHeader eyebrow="WORKSPACE" title="数字人对话" description="选择运行时并观察从会话、RAG 到 Provider 的完整链路。" actions={<span className="page-live"><Activity size={14} />实时工作台</span>} />
      <RuntimeStrip provider={avatar.selected} />
      <div className="home-grid">
        <aside className="home-provider"><ProviderPanel providers={avatar.providers} selectedProvider={avatar.selectedProvider} selected={avatar.selected} session={avatar.session} isLoading={avatar.isLoading} isCreating={avatar.isCreating} error={avatar.error} onSelect={avatar.setSelectedProvider} onCreate={() => void avatar.create()} onClose={() => void avatar.close()} onRefresh={() => void avatar.loadProviders()} onClearError={avatar.clearError} /></aside>
        <ChatPanel session={avatar.session} messages={chat.messages} timeline={chat.timeline} isSending={chat.isSending} error={chat.error} onSend={(message) => void chat.sendMessage(message)} onStop={chat.stop} onClear={chat.clear} />
        <aside className="home-timeline"><EventTimeline items={chat.timeline} /></aside>
      </div>
    </div>
  )
}
