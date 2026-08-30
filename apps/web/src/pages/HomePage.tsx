import { History } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { useAvatar } from '../features/avatar/model'
import type { useChat } from '../features/chat/model'
import type { useRealtimeSession } from '../features/realtime/model'
import { AvatarStage } from '../features/avatar/components/AvatarStage'
import { ConversationDrawer } from '../features/chat/components/ConversationDrawer'
import { HomeConversationBar } from '../features/chat/components/HomeConversationBar'

type AvatarState = ReturnType<typeof useAvatar>
type ChatState = ReturnType<typeof useChat>
type RealtimeState = ReturnType<typeof useRealtimeSession>

interface HomePageProps {
  avatar: AvatarState
  chat: ChatState
  realtime: RealtimeState
}

export function HomePage({ avatar, chat, realtime }: HomePageProps) {
  const [drawerOpen, setDrawerOpen] = useState(false)

  useEffect(() => {
    if (!avatar.session) {
      void realtime.disconnect()
      return
    }
    const timer = window.setTimeout(() => void realtime.connect(), 0)
    return () => window.clearTimeout(timer)
  }, [avatar.session?.sessionId, realtime.connect, realtime.disconnect])

  return (
    <div className="page-stack home-page">
      <main className="home-reference-stage">
        <AvatarStage session={avatar.session} realtime={realtime.state} onCreate={() => void avatar.create()} />
        <HomeConversationBar session={avatar.session} realtime={realtime} isSending={chat.isSending} onSend={(message) => void chat.sendMessage(message)} />
        <button className="conversation-toggle" type="button" title="打开对话记录" aria-label="打开对话记录" aria-expanded={drawerOpen} onClick={() => setDrawerOpen(true)}>
          <History size={18} />
        </button>
      </main>
      <ConversationDrawer open={drawerOpen} messages={chat.messages} onClose={() => setDrawerOpen(false)} onClear={chat.clear} />
    </div>
  )
}
