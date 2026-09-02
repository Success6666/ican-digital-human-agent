import { sanitizeDisplayText } from '../../shared/lib/format'
import type { AvatarClientParams } from '../../shared/api/types'
import type { RealtimeClientConfig, RealtimeInboundEvent } from './types'

const DEFAULT_ENDPOINT = '/api/realtime'
const DEFAULT_PROTOCOL = 'realtime.v1'
const DEFAULT_SAMPLE_RATE = 16_000
const DEFAULT_FRAME_MS = 20
const DEFAULT_MAX_FRAME_BYTES = 256 * 1024
const DEFAULT_HEARTBEAT_MS = 30_000

export function buildRealtimeConfig(
  sessionId: string,
  params?: AvatarClientParams,
): RealtimeClientConfig {
  const nested = params?.realtime
  const endpoint = firstText(
    DEFAULT_ENDPOINT,
    nested?.endpoint,
    nested?.wsUrl,
    nested?.websocketUrl,
    params?.endpoint,
    params?.wsUrl,
    params?.websocketUrl,
    params?.realtimeUrl,
  )
  return {
    endpoint: resolveEndpoint(endpoint),
    protocol: firstText(DEFAULT_PROTOCOL, nested?.protocol, params?.protocol),
    sessionId,
    sampleRate: boundedNumber(nested?.sampleRate ?? params?.sampleRate, DEFAULT_SAMPLE_RATE, 8_000, 96_000),
    channels: boundedInteger(nested?.channels ?? params?.channels, 1, 1, 2) as 1 | 2,
    frameMs: boundedNumber(nested?.frameMs ?? params?.frameMs, DEFAULT_FRAME_MS, 10, 100),
    codec: firstText('pcm_s16le', nested?.codec, params?.codec),
    maxFrameBytes: boundedInteger(nested?.maxFrameBytes ?? params?.maxFrameBytes, DEFAULT_MAX_FRAME_BYTES, 320, 1_048_576),
    heartbeatMs: boundedInteger(nested?.heartbeatMs ?? params?.heartbeatMs, DEFAULT_HEARTBEAT_MS, 5_000, 300_000),
    accessToken: optionalFirstText(nested?.accessToken, params?.accessToken),
    ticket: optionalFirstText(nested?.ticket, params?.ticket),
  }
}

export function resolveEndpoint(value: string): string {
  const candidate = value.trim()
  if (!candidate) return defaultEndpoint()
  try {
    const base = typeof window === 'undefined' ? 'http://localhost' : window.location.href
    const parsed = new URL(candidate, base)
    const current = new URL(base)
    const path = parsed.pathname.replace(/\/+$/, '') || '/'
    const sameAuthority = parsed.host === current.host
    const supportedProtocol = ['http:', 'https:', 'ws:', 'wss:'].includes(parsed.protocol)
    if (!sameAuthority || !supportedProtocol || path !== DEFAULT_ENDPOINT) return defaultEndpoint()
    parsed.pathname = DEFAULT_ENDPOINT
    parsed.search = ''
    parsed.hash = ''
    if (parsed.protocol === 'http:') parsed.protocol = 'ws:'
    if (parsed.protocol === 'https:') parsed.protocol = 'wss:'
    if (parsed.protocol !== 'ws:' && parsed.protocol !== 'wss:') return defaultEndpoint()
    return parsed.toString().slice(0, 4096)
  } catch {
    return defaultEndpoint()
  }
}

export function controlFrame(
  type: 'hello' | 'text' | 'interrupt' | 'audio_start' | 'audio_end' | 'speech_start' | 'speech_end' | 'ping' | 'pong' | 'close',
  payload: Record<string, unknown>,
): string {
  return JSON.stringify({ type, ...payload })
}

export async function decodeRealtimeMessage(raw: unknown): Promise<RealtimeInboundEvent | null> {
  if (raw instanceof ArrayBuffer) return { type: 'audio_queue', data: raw }
  if (ArrayBuffer.isView(raw)) {
    const view = raw as ArrayBufferView
    const bytes = new Uint8Array(view.buffer, view.byteOffset, view.byteLength)
    return { type: 'audio_queue', data: bytes.slice().buffer }
  }
  if (typeof Blob !== 'undefined' && raw instanceof Blob) {
    return { type: 'audio_queue', data: await raw.arrayBuffer() }
  }
  if (typeof raw !== 'string') return null
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return { type: 'error', message: '实时通道返回了无法识别的数据' }
  }
  if (!isRecord(value)) return { type: 'error', message: '实时通道返回格式无效' }
  return normalizeInbound(value)
}

export function normalizeInbound(value: Record<string, unknown>): RealtimeInboundEvent {
  const type = String(value.type ?? value.event ?? 'message').trim().toLowerCase()
  const event: RealtimeInboundEvent = {
    ...value,
    type,
    eventId: optionalText(value.eventId ?? value.event_id, 128),
    requestId: optionalText(value.requestId ?? value.request_id, 128),
    sessionId: optionalText(value.sessionId ?? value.session_id, 128),
    connectionId: optionalText(value.connectionId ?? value.connection_id, 128),
    runId: optionalText(value.runId ?? value.run_id, 128),
    utteranceId: optionalText(value.utteranceId ?? value.utterance_id, 128),
    revision: optionalInteger(value.revision, 0, Number.MAX_SAFE_INTEGER),
    seq: optionalInteger(value.seq ?? value.sequence, 0, Number.MAX_SAFE_INTEGER),
    status: optionalText(value.status, 48),
    text: optionalDisplayText(value.text ?? value.transcript ?? value.reply, 4_000),
    message: optionalDisplayText(value.message ?? value.error, 180),
    reason: optionalDisplayText(value.reason, 180),
    action: optionalText(value.action, 64),
    phase: optionalText(value.phase, 48),
    codec: optionalText(value.codec, 64),
    sampleRate: optionalInteger(value.sampleRate ?? value.sample_rate, 8_000, 96_000),
    channels: optionalInteger(value.channels, 1, 2),
    frameMs: optionalInteger(value.frameMs ?? value.frame_ms, 10, 100),
    heartbeatMs: optionalInteger(value.heartbeatMs ?? value.heartbeat_ms, 1_000, 300_000),
    audioQueueMs: optionalNumber(value.audioQueueMs ?? value.audio_queue_ms, 0, 60_000),
    queueDepth: optionalInteger(value.queueDepth ?? value.queue_depth, 0, 100_000),
    bufferedBytes: optionalInteger(value.bufferedBytes ?? value.buffered_bytes, 0, 4 * 1024 * 1024),
    capabilities: normalizeRecord(value.capabilities),
    audioFormat: normalizeRecord(value.audioFormat ?? value.audio_format),
    limits: normalizeRecord(value.limits),
  }
  const base64 = optionalText(value.audioBase64 ?? value.audio_base64 ?? value.audio, 1_048_576)
  if (base64) {
    const decoded = decodeBase64(base64)
    if (decoded) event.data = decoded
  }
  return event
}

function decodeBase64(value: string): ArrayBuffer | undefined {
  try {
    if (typeof atob !== 'function') return undefined
    const binary = atob(value)
    const bytes = new Uint8Array(binary.length)
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
    return bytes.buffer
  } catch {
    return undefined
  }
}

function firstText(fallback: string, ...values: Array<unknown>): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return fallback
}

function defaultEndpoint(): string {
  if (typeof window === 'undefined') return DEFAULT_ENDPOINT
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${DEFAULT_ENDPOINT}`
}

function optionalFirstText(...values: Array<unknown>): string | undefined {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim().slice(0, 2048)
  }
  return undefined
}

function boundedNumber(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : NaN
  return Number.isFinite(parsed) && parsed >= min && parsed <= max ? parsed : fallback
}

function boundedInteger(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = boundedNumber(value, fallback, min, max)
  return Number.isInteger(parsed) ? parsed : fallback
}

function optionalNumber(value: unknown, min: number, max: number): number | undefined {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : NaN
  return Number.isFinite(parsed) && parsed >= min && parsed <= max ? parsed : undefined
}

function optionalInteger(value: unknown, min: number, max: number): number | undefined {
  const parsed = optionalNumber(value, min, max)
  return parsed !== undefined && Number.isInteger(parsed) ? parsed : undefined
}

function optionalText(value: unknown, limit: number): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = value.trim()
  return normalized ? normalized.slice(0, limit) : undefined
}

function optionalDisplayText(value: unknown, limit: number): string | undefined {
  const text = optionalText(value, limit)
  return text ? sanitizeDisplayText(text, limit) : undefined
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function normalizeRecord(value: unknown): Record<string, unknown> | undefined {
  return isRecord(value) ? value : undefined
}
