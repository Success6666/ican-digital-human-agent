import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { clearToken, getToken, setToken } from '../../shared/api/client'
import type { LoginRequest, User } from '../../shared/api/types'
import * as authApi from './api'

interface AuthContextValue {
  user: User | null
  token: string | null
  isLoading: boolean
  error: string | null
  login: (request: LoginRequest) => Promise<void>
  logout: () => Promise<void>
  clearError: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setTokenState] = useState<string | null>(() => getToken())
  const [isLoading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const onExpired = () => {
      clearToken()
      setTokenState(null)
      setUser(null)
      setError('登录状态已过期，请重新登录')
    }
    window.addEventListener('auth:expired', onExpired)
    return () => window.removeEventListener('auth:expired', onExpired)
  }, [])

  useEffect(() => {
    let cancelled = false
    async function hydrate() {
      try {
        const currentUser = await authApi.getCurrentUser()
        if (!cancelled) setUser(currentUser)
      } catch {
        if (!cancelled) {
          clearToken()
          setTokenState(null)
          setUser(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void hydrate()
    return () => { cancelled = true }
  }, [token])

  const value = useMemo<AuthContextValue>(() => ({
    user,
    token,
    isLoading,
    error,
    clearError: () => setError(null),
    login: async (request) => {
      setLoading(true)
      setError(null)
      try {
        const response = await authApi.login(request)
        // Sa-Token's HttpOnly cookie is the browser source of truth. Keep the
        // returned token only in memory for explicit cross-origin dev setups.
        setToken(response.token)
        setTokenState(response.token)
        setUser(response.user)
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : '登录失败，请稍后重试')
        throw cause
      } finally {
        setLoading(false)
      }
    },
    logout: async () => {
      try {
        await authApi.logout()
      } catch {
        // 即使网关暂时不可用，也清理本地凭证，避免留下失效会话。
      } finally {
        clearToken()
        setTokenState(null)
        setUser(null)
      }
    },
  }), [error, isLoading, token, user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return context
}
