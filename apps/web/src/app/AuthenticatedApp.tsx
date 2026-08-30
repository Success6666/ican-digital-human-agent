import { useEffect, useState } from 'react'
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
  const chat = useChat(avatar.session)
  const realtime = useRealtimeSession(avatar.session, { onInterrupt: chat.stop })
  const [page, setPage] = useState<PageKey>(() => pageFromHash(window.location.hash))

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

  const content = page === 'rag' ? <RagPage /> : page === 'evaluation' ? <EvaluationPage /> : page === 'audit' ? <AuditPage /> : page === 'settings' ? <SettingsPage avatar={avatar} canManage={user?.role === 'admin'} /> : <HomePage avatar={avatar} chat={chat} realtime={realtime} />
  return <ConsoleShell user={user} activePage={page} onNavigate={navigate} onLogout={handleLogout}>{content}</ConsoleShell>
}
