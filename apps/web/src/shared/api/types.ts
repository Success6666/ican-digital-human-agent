export interface User {
  id: string
  username?: string
  name: string
  role?: string
  avatarUrl?: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  token: string
  user: User
}

export type ProviderName = 'mock' | 'aliyun' | 'mofa' | 'iflytek' | 'fay' | string

export interface ProviderStatus {
  name: ProviderName
  label: string
  description?: string
  configured: boolean
  available: boolean
  capabilities: string[]
  latencyMs?: number
}

export interface AvatarSession {
  sessionId: string
  provider: ProviderName
  capabilities: string[]
  expiresAt?: string
  status?: 'active' | 'closed' | 'expired' | string
}

export interface ToolCall {
  name: string
  status?: 'running' | 'completed' | 'failed' | string
  input?: unknown
  output?: unknown
  durationMs?: number
}

export interface ChatRequest {
  sessionId: string
  message: string
}

export interface ChatResponse {
  reply: string
  traceId?: string
  toolCalls?: ToolCall[]
}

export type ChatEventType = 'start' | 'filler' | 'intent' | 'disclosure' | 'security' | 'rag' | 'tool' | 'provider' | 'delta' | 'done' | 'interrupted' | 'error' | string

export interface AvatarPerformanceCue {
  expression?: string
  intensity?: number
  durationMs?: number
  gaze?: string
  gesture?: string
  lipSync?: boolean
  [key: string]: unknown
}

export interface ChatToolDisclosure {
  name?: string
  label?: string
  description?: string
}

export interface ChatStreamEvent {
  type: ChatEventType
  eventId?: string
  seq?: number
  traceId?: string
  text?: string
  reply?: string
  toolCall?: ToolCall
  toolCalls?: ToolCall[]
  tools?: ChatToolDisclosure[]
  intent?: string
  confidence?: number
  source?: string
  performance?: AvatarPerformanceCue
  interrupted?: boolean
  hitCount?: number
  degraded?: boolean
  message?: string
  [key: string]: unknown
}
