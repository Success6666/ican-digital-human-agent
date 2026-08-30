import { api } from '../../shared/api/client'
import type { AvatarSession, ProviderName, ProviderStatus } from '../../shared/api/types'
import { capabilityNames } from './capabilities'
import { normalizeClientParams } from './clientParams'

interface ProviderListResponse {
  providers?: ProviderWire[]
}

export interface ProviderWire {
  name?: ProviderName
  provider?: ProviderName
  label?: string
  status?: string
  configured?: boolean
  available?: boolean
  detail?: string
  description?: string
  capabilities?: string[] | Record<string, unknown>
}

interface SessionResponse {
  session?: AvatarSession
  sessionId?: string
  provider?: ProviderName
  capabilities?: string[] | Record<string, unknown>
  expiresAt?: string
  status?: string
  clientParams?: unknown
}

export async function listProviders(): Promise<ProviderWire[]> {
  const response = await api.get<ProviderWire[] | ProviderListResponse>('/providers')
  return Array.isArray(response) ? response : response.providers ?? []
}

export async function createSession(provider: ProviderName): Promise<AvatarSession> {
  const response = await api.post<AvatarSession | SessionResponse>('/sessions', { provider })
  if ('sessionId' in response) {
    return {
      sessionId: response.sessionId as string,
      provider: response.provider ?? provider,
      capabilities: capabilityNames(response.capabilities),
      expiresAt: response.expiresAt,
      status: response.status,
      clientParams: normalizeClientParams(response.clientParams),
    }
  }
  if (response.session) {
    return {
      ...response.session,
      capabilities: capabilityNames(response.session.capabilities),
      clientParams: normalizeClientParams(response.session.clientParams),
    }
  }
  throw new Error('服务端未返回有效会话')
}

export async function closeSession(sessionId: string): Promise<void> {
  await api.delete(`/sessions/${encodeURIComponent(sessionId)}`)
}
