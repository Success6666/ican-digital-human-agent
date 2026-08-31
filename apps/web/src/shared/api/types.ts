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
  default?: boolean
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
  /**
   * 仅包含当前已认证会话的浏览器 Runtime 参数。具体字段由供应商白名单控制。
   */
  clientParams?: AvatarClientParams
}

export interface AvatarClientParams {
  runtime?: string
  endpoint?: string
  wsUrl?: string
  websocketUrl?: string
  realtimeUrl?: string
  protocol?: string
  codec?: string
  sampleRate?: number
  channels?: number
  frameMs?: number
  maxFrameBytes?: number
  heartbeatMs?: number
  accessToken?: string
  ticket?: string
  expiresAt?: string
  sdkUrl?: string
  cryptoUrl?: string
  gatewayServer?: string
  appId?: string
  appSecret?: string
  authorization?: string
  dataSource?: string
  customId?: string
  realtime?: {
    endpoint?: string
    wsUrl?: string
    websocketUrl?: string
    protocol?: string
    codec?: string
    sampleRate?: number
    channels?: number
    frameMs?: number
    maxFrameBytes?: number
    heartbeatMs?: number
    accessToken?: string
    ticket?: string
    expiresAt?: string
  }
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
  runId?: string
  toolCalls?: ToolCall[]
  agentResponse?: AgentResponse
  agentLatencyMs?: number
  digitalHumanLatencyMs?: number
  firstEventLatencyMs?: number
  firstVisibleLatencyMs?: number
  cancellationLatencyMs?: number
}

export interface AgentResponse {
  text: string
  emotion?: string
  gesture?: string
  presentation?: AvatarPerformanceCue
  performance?: AvatarPerformanceCue
  traceId?: string
  sessionId?: string
  runId?: string
  interruptible?: boolean
}

export type ChatEventType = 'start' | 'filler' | 'intent' | 'disclosure' | 'security' | 'rag' | 'tool' | 'provider' | 'delta' | 'done' | 'interrupted' | 'error' | string

export interface AvatarPerformanceCue {
  expression?: string
  intensity?: number
  durationMs?: number
  gaze?: string
  gesture?: string
  action?: string
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
  runId?: string
  text?: string
  reply?: string
  toolCall?: ToolCall
  toolCalls?: ToolCall[]
  tools?: ChatToolDisclosure[]
  intent?: string
  confidence?: number
  source?: string
  performance?: AvatarPerformanceCue
  presentation?: AvatarPerformanceCue
  interrupted?: boolean
  hitCount?: number
  degraded?: boolean
  message?: string
  [key: string]: unknown
}
