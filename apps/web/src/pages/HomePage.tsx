import { History } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
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
  const [drawerMessages, setDrawerMessages] = useState(chat.messages)
  const [drawerConversations, setDrawerConversations] = useState(chat.conversations)
  const chatActionsRef = useRef({
    clear: chat.clear,
    newConversation: chat.newConversation,
    selectConversation: chat.selectConversation,
    deleteConversation: chat.deleteConversation,
  })
  chatActionsRef.current = {
    clear: chat.clear,
    newConversation: chat.newConversation,
    selectConversation: chat.selectConversation,
    deleteConversation: chat.deleteConversation,
  }
  const latestAssistant = [...chat.messages].reverse().find((message) => message.role === 'assistant' && (message.content.trim() || message.statusText?.trim()))
  const latestUser = [...chat.messages].reverse().find((message) => message.role === 'user')
  const [avatarSpeaking, setAvatarSpeaking] = useState(false)
  const [avatarReady, setAvatarReady] = useState(false)
  const realtimeAssistant = realtime.state.assistantText.trim()
  const pendingApproval = [...chat.timeline].reverse().find((item) => item.approvalId && item.approvalStatus === 'pending')
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

  const openConversationDrawer = useCallback(() => {
    setDrawerMessages(chat.messages.map((message) => ({ ...message, pending: false, statusText: undefined })))
    setDrawerConversations(chat.conversations.map((conversation) => ({
      ...conversation,
      messages: conversation.messages.map((message) => ({ ...message, pending: false, statusText: undefined })),
    })))
    setDrawerOpen(true)
  }, [chat.conversations, chat.messages])
  const closeConversationDrawer = useCallback(() => setDrawerOpen(false), [])
  const clearConversationDrawer = useCallback(() => {
    chatActionsRef.current.clear()
    setDrawerMessages([])
  }, [])
  const newConversationFromDrawer = useCallback(() => {
    chatActionsRef.current.newConversation()
    setDrawerOpen(false)
  }, [])
  const selectConversationFromDrawer = useCallback((conversationId: string) => {
    chatActionsRef.current.selectConversation(conversationId)
    setDrawerOpen(false)
  }, [])
  const deleteConversationFromDrawer = useCallback((conversationId: string) => {
    chatActionsRef.current.deleteConversation(conversationId)
    setDrawerConversations((current) => current.filter((conversation) => conversation.id !== conversationId))
  }, [])

  return (
    <div className="page-stack home-page">
      <main className="home-reference-stage">
        <AvatarStage
          session={avatar.session}
          visible={visible}
          isCreating={avatar.isCreating}
          speech={activeSpeech}
          interruptKey={avatarSpeaking ? latestUser?.id : undefined}
          activate={chat.isSending || realtime.state.recording === 'recording' || realtime.state.recording === 'requesting'}
          onCreate={() => void avatar.create()}
          onDisconnect={() => void avatar.close()}
          onSpeakingChange={setAvatarSpeaking}
          onReadyChange={setAvatarReady}
        />
        <HomeConversationBar session={avatar.session} realtime={realtime} isSending={chat.isSending} isCreating={avatar.isCreating} avatarReady={avatarReady} avatarSpeaking={avatarSpeaking} onSend={(message) => void chat.sendMessage(message)} pendingApproval={pendingApproval?.approvalId ? { id: pendingApproval.approvalId, title: pendingApproval.title } : undefined} onApproval={(approvalId, approved) => void chat.resolveApproval(approvalId, approved)} />
        <button className="conversation-toggle" type="button" title="打开对话记录" aria-label="打开对话记录" aria-expanded={drawerOpen} onClick={openConversationDrawer}>
          <History size={18} />
        </button>
      </main>
      <ConversationDrawer
        open={drawerOpen}
        messages={drawerMessages}
        conversations={drawerConversations}
        activeConversationId={chat.activeConversationId}
        onClose={closeConversationDrawer}
        onClear={clearConversationDrawer}
        onNew={newConversationFromDrawer}
        onSelect={selectConversationFromDrawer}
        onDelete={deleteConversationFromDrawer}
      />
    </div>
  )
}
