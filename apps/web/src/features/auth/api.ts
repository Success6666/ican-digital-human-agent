import { api } from '../../shared/api/client'
import type { LoginRequest, LoginResponse, User } from '../../shared/api/types'

interface UserWire {
  id: string
  username?: string
  name?: string
  displayName?: string
  role?: string
}

interface LoginWire {
  token: string
  user: UserWire
}

function normalizeUser(user: UserWire): User {
  return {
    id: user.id,
    username: user.username,
    name: user.name || user.displayName || user.username || user.id,
    role: user.role,
  }
}

export async function login(request: LoginRequest): Promise<LoginResponse> {
  const response = await api.post<LoginWire>('/auth/login', request)
  return { token: response.token, user: normalizeUser(response.user) }
}

export async function getCurrentUser(): Promise<User> {
  const response = await api.get<UserWire | { user: UserWire }>('/auth/me')
  return normalizeUser('user' in response ? response.user : response)
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout')
}
