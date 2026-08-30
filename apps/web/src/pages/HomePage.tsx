import { Activity } from 'lucide-react'
import type { useAvatar } from '../features/avatar/model'
import type { useChat } from '../features/chat/model'
import type { useRealtimeSession } from '../features/realtime/model'
import { ProviderPanel } from '../features/avatar/components/ProviderPanel'
import { AvatarStage } from '../features/avatar/components/AvatarStage'
import { ChatPanel } from '../features/chat/components/ChatPanel'
import { EventTimeline } from '../features/chat/components/EventTimeline'
import { RealtimePanel } from '../features/realtime/components/RealtimePanel'
import { RuntimeStrip } from '../features/runtime/components/RuntimeStrip'
import { PageHeader } from '../shared/components/PageHeader'

type AvatarState = ReturnType<typeof useAvatar>
type ChatState = ReturnType<typeof useChat>
type RealtimeState = ReturnType<typeof useRealtimeSession>

interface HomePageProps {
  avatar: AvatarState
  chat: ChatState
  realtime: RealtimeState
}

export function HomePage({ avatar, chat, realtime }: HomePageProps) {
  return (
    <div className="page-stack home-page">
      <PageHeader eyebrow="WORKSPACE" title="数字人工作台" description="在一个视图里建立会话、实时交流，并观察 Agent 到数字人的完整链路。" actions={<div className="page-header-actions"><span className="page-live"><Activity size={14} />实时工作台</span></div>} />
      <RuntimeStrip provider={avatar.selected} />
      <div className="home-grid">
        <aside className="home-provider"><ProviderPanel providers={avatar.providers} selectedProvider={avatar.selectedProvider} selected={avatar.selected} session={avatar.session} isLoading={avatar.isLoading} isCreating={avatar.isCreating} error={avatar.error} onSelect={avatar.setSelectedProvider} onCreate={() => void avatar.create()} onClose={() => void avatar.close()} onRefresh={() => void avatar.loadProviders()} onClearError={avatar.clearError} /></aside>
        <div className="home-center">
          <AvatarStage provider={avatar.selected} session={avatar.session} realtime={realtime.state} onCreate={() => void avatar.create()} />
          <RealtimePanel realtime={realtime} />
          <ChatPanel session={avatar.session} messages={chat.messages} timeline={chat.timeline} isSending={chat.isSending} error={chat.error} onSend={(message) => void chat.sendMessage(message)} onStop={chat.stop} onClear={chat.clear} />
        </div>
        <aside className="home-timeline"><EventTimeline items={chat.timeline} /></aside>
      </div>
    </div>
  )
}
