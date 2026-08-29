import { LoginForm } from '../features/auth/components/LoginForm'
import { AuthProvider, useAuth } from '../features/auth/model'
import { AuthenticatedApp } from './AuthenticatedApp'

function LoadingScreen() {
  return <div className="loading-screen"><div className="brand-mark brand-mark--large"><span /></div><span>正在连接控制台…</span></div>
}

function AppContent() {
  const { user, isLoading } = useAuth()
  if (isLoading) return <LoadingScreen />
  return user ? <AuthenticatedApp /> : <LoginForm />
}

export default function App() {
  return <AuthProvider><AppContent /></AuthProvider>
}
