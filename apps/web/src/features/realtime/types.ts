import type { AvatarClientParams } from '../../shared/api/types'

export type RealtimeConnectionState =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'closed'
  | 'unsupported'
  | 'error'

export type RealtimeRecordingState =
  | 'idle'
  | 'requesting'
  | 'recording'
  | 'stopping'
  | 'unsupported'
  | 'error'

export type RealtimePlaybackState = 'idle' | 'playing' | 'interrupted' | 'error'

export type RealtimePhase =
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'interrupting'
  | 'degraded'
  | 'error'

export interface RealtimeState {
  connection: RealtimeConnectionState
  textSupported: boolean
  audioSupported: boolean
  audioOutputSupported: boolean
  asrStatus: 'unknown' | 'supported' | 'unsupported'
  ttsStatus: 'unknown' | 'supported' | 'unsupported'
  recording: RealtimeRecordingState
  playback: RealtimePlaybackState
  phase: RealtimePhase
  sessionId?: string
  connectionId?: string
  runId?: string
  utteranceId?: string
  revision: number
  interimTranscript: string
  transcript: string
  assistantText: string
  statusText: string
  error?: string
  droppedFrames: number
  bufferedBytes: number
  lastEventAt?: string
}

export const initialRealtimeState: RealtimeState = {
  connection: 'idle',
  textSupported: false,
  audioSupported: false,
  audioOutputSupported: false,
  asrStatus: 'unknown',
  ttsStatus: 'unknown',
  recording: 'idle',
  playback: 'idle',
  phase: 'idle',
  revision: 0,
  interimTranscript: '',
  transcript: '',
  assistantText: '',
  statusText: '当前仅支持文本实时链路',
  droppedFrames: 0,
  bufferedBytes: 0,
}

export type RealtimeAction =
  | { type: 'reset'; sessionId?: string; supported: boolean; textSupported?: boolean }
  | { type: 'connection'; state: RealtimeConnectionState; message?: string; connectionId?: string }
  | { type: 'recording'; state: RealtimeRecordingState; message?: string }
  | { type: 'capabilities'; audioInput?: boolean; audioOutput?: boolean; asr?: unknown; tts?: unknown }
  | { type: 'playback'; state: RealtimePlaybackState; message?: string }
  | { type: 'phase'; phase: RealtimePhase; message?: string }
  | { type: 'revision'; utteranceId?: string; revision: number }
  | { type: 'run'; runId?: string }
  | { type: 'transcript'; status: 'partial' | 'final' | 'unsupported'; text?: string }
  | { type: 'assistant'; text: string; append?: boolean }
  | { type: 'buffer'; bytes: number; dropped?: number }
  | { type: 'error'; message: string; fatal?: boolean }
  | { type: 'event'; at?: string }

export interface RealtimeClientConfig {
  endpoint: string
  protocol: string
  sessionId: string
  sampleRate: number
  channels: 1 | 2
  frameMs: number
  codec: string
  maxFrameBytes: number
  heartbeatMs: number
  audioFrameBytes?: number
  maxAudioFrameBytes?: number
  maxAudioBufferBytes?: number
  accessToken?: string
  ticket?: string
}

export interface RealtimeInboundEvent {
  type: string
  eventId?: string
  requestId?: string
  sessionId?: string
  connectionId?: string
  runId?: string
  utteranceId?: string
  revision?: number
  seq?: number
  status?: string
  text?: string
  message?: string
  reason?: string
  accepted?: boolean
  action?: string
  phase?: string
  codec?: string
  sampleRate?: number
  channels?: number
  frameMs?: number
  heartbeatMs?: number
  data?: ArrayBuffer
  audioBase64?: string
  audioQueueMs?: number
  queueDepth?: number
  bufferedBytes?: number
  capabilities?: Record<string, unknown>
  audioFormat?: Record<string, unknown>
  limits?: Record<string, unknown>
  [key: string]: unknown
}

export interface RealtimeSocketHandlers {
  onOpen?: () => void
  onClose?: (event: CloseEvent) => void
  onError?: (message: string) => void
  onMessage?: (event: RealtimeInboundEvent) => void
  onState?: (state: RealtimeConnectionState) => void
}

export interface RealtimeSocketOptions extends RealtimeSocketHandlers {
  endpoint: string
  protocols?: string | string[]
  handshakeTimeoutMs?: number
  maxReconnectAttempts?: number
}

export interface PcmRecorderOptions {
  sampleRate?: number
  channels?: 1 | 2
  frameMs?: number
  maxPendingBytes?: number
  onChunk: (frame: ArrayBuffer) => boolean | void
  onDrop?: (count: number) => void
}

export interface PcmPlaybackOptions {
  sampleRate?: number
  channels?: 1 | 2
  maxQueueMs?: number
  onState?: (state: RealtimePlaybackState) => void
  onDrop?: (count: number) => void
}

export interface RealtimeSessionOptions {
  onTranscript?: (text: string) => void
  onAssistantText?: (text: string, append: boolean) => void
  onInterrupt?: () => void
}

export function hasAudioInput(session?: { capabilities?: string[]; clientParams?: AvatarClientParams } | null): boolean {
  if (!session) return false
  const params = session.clientParams
  if (
    params?.endpoint || params?.wsUrl || params?.websocketUrl || params?.realtimeUrl
    || params?.realtime?.endpoint || params?.realtime?.wsUrl || params?.realtime?.websocketUrl
    || params?.realtime?.sampleRate || params?.sampleRate
  ) {
    return true
  }
  return (session.capabilities ?? []).some((value) => {
    const normalized = String(value).toLowerCase()
    return normalized.includes('audio') || normalized.includes('语音')
  })
}
