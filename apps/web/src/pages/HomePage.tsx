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
  visible?: boolean
}

export function HomePage({ avatar, chat, realtime, visible = true }: HomePageProps) {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const latestAssistant = [...chat.messages].reverse().find((message) => message.role === 'assistant' && (message.content.trim() || message.statusText?.trim()))
  const latestUser = [...chat.messages].reverse().find((message) => message.role === 'user')
  const [queuedMessage, setQueuedMessage] = useState<string | null>(null)
  const [avatarSpeaking, setAvatarSpeaking] = useState(false)
  const realtimeAssistant = realtime.state.assistantText.trim()
  const activeSpeech = realtimeAssistant ? {
    id: `realtime-${realtime.state.utteranceId ?? realtime.state.revision}:${realtimeAssistant.length}:${realtime.state.phase}`,
    text: realtimeAssistant,
    pending: realtime.state.phase === 'speaking',
  } : latestAssistant ? {
    id: `${latestAssistant.id}:${latestAssistant.content.length}:${latestAssistant.statusText?.length ?? 0}:${latestAssistant.pending ? 'streaming' : 'final'}`,
    text: latestAssistant.content || latestAssistant.statusText || '',
    presentation: latestAssistant.presentation,
    pending: latestAssistant.content ? latestAssistant.pending : false,
  } : undefined

  useEffect(() => {
    if (!avatar.session) {
      void realtime.disconnect()
      return
    }
    const timer = window.setTimeout(() => void realtime.connect(), 0)
    return () => window.clearTimeout(timer)
  }, [avatar.session?.sessionId, realtime.connect, realtime.disconnect])

  useEffect(() => {
    if (!avatar.session || !queuedMessage) return
    const message = queuedMessage
    setQueuedMessage(null)
    void chat.sendMessage(message)
  }, [avatar.session?.sessionId, chat.sendMessage, queuedMessage])

  function startConversation(message?: string) {
    if (message) setQueuedMessage(message)
    void avatar.create().catch(() => setQueuedMessage(null))
  }

  return (
    <div className="page-stack home-page">
      <main className="home-reference-stage">
        <AvatarStage
          session={avatar.session}
          visible={visible}
          isCreating={avatar.isCreating}
          speech={activeSpeech}
          interruptKey={latestUser?.id}
          activate={chat.isSending || realtime.state.recording === 'recording' || realtime.state.recording === 'requesting'}
          onCreate={() => void avatar.create()}
          onDisconnect={() => void avatar.close()}
          onSpeakingChange={setAvatarSpeaking}
        />
        <HomeConversationBar session={avatar.session} realtime={realtime} isSending={chat.isSending} isCreating={avatar.isCreating} avatarSpeaking={avatarSpeaking} onSend={(message) => void chat.sendMessage(message)} onCreateSession={startConversation} />
        <button className="conversation-toggle" type="button" title="打开对话记录" aria-label="打开对话记录" aria-expanded={drawerOpen} onClick={() => setDrawerOpen(true)}>
          <History size={18} />
        </button>
      </main>
      <ConversationDrawer open={drawerOpen} messages={chat.messages} onClose={() => setDrawerOpen(false)} onClear={chat.clear} />
    </div>
  )
}
