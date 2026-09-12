import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../features/auth/model'
import { useAvatar } from '../features/avatar/model'
import { useChat } from '../features/chat/model'
import { useRealtimeSession } from '../features/realtime/model'
import { AuditPage } from '../pages/AuditPage'
import { EvaluationPage } from '../pages/EvaluationPage'
import { HomePage } from '../pages/HomePage'
import { RagPage } from '../pages/RagPage'
import { SettingsPage } from '../pages/SettingsPage'
import { ConsoleShell } from '../shared/components/ConsoleShell'
import { pageAllowedForRole, pageFromHash, pageToHash, type PageKey } from '../shared/navigation'

export function AuthenticatedApp() {
  const { user, logout } = useAuth()
  const avatar = useAvatar()
  const chat = useChat(avatar.session, user?.id)
  const realtime = useRealtimeSession(avatar.session, {
    onInterrupt: chat.stop,
    // Voice turns now land in the shared conversation record. The realtime
    // channel has always carried the final transcript and the reply deltas;
    // nothing ever handed them to the chat model, so the drawer showed no
    // spoken turn and the agent context lost the whole voice conversation.
    onTranscript: (text) => chat.beginVoiceTurn(text),
    onAssistantText: (text, append) => chat.appendVoiceAssistant(text, append),
  })
  const [page, setPage] = useState<PageKey>(() => pageFromHash(window.location.hash))
  // A voice reply is only "done" when the session leaves thinking/speaking.
  // Tracking the previous phase keeps the finalizer edge-triggered: without it,
  // every idle render would re-run the effect and the pending placeholder would
  // be cleared before the first delta even arrives.
  const realtimePhaseRef = useRef(realtime.state.phase)
  useEffect(() => {
    const previous = realtimePhaseRef.current
    realtimePhaseRef.current = realtime.state.phase
    if (previous !== 'idle' && realtime.state.phase === 'idle') chat.finishVoiceTurn()
  }, [realtime.state.phase, chat.finishVoiceTurn])

  useEffect(() => {
    const onHashChange = () => setPage(pageFromHash(window.location.hash))
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  useEffect(() => {
    if (user && !pageAllowedForRole(page, user.role)) navigate('home')
  }, [page, user])

  function navigate(next: PageKey) {
    if (next === page) return
    window.history.replaceState(null, '', pageToHash(next))
    setPage(next)
  }

  async function handleLogout() {
    await realtime.disconnect()
    await avatar.close()
    await logout()
  }

  const content = page === 'rag' ? <RagPage /> : page === 'evaluation' ? <EvaluationPage /> : page === 'audit' ? <AuditPage /> : page === 'settings' ? <SettingsPage avatar={avatar} canManage={user?.role === 'admin'} /> : null
  return <ConsoleShell user={user} activePage={page} onNavigate={navigate} onLogout={handleLogout}>
    <div className={`page-cache-layer ${page === 'home' ? 'page-cache-layer--active' : 'page-cache-layer--hidden'}`} aria-hidden={page !== 'home'}>
      <HomePage avatar={avatar} chat={chat} realtime={realtime} visible={page === 'home'} />
    </div>
    {content && <div className="active-page-layer">{content}</div>}
  </ConsoleShell>
}
