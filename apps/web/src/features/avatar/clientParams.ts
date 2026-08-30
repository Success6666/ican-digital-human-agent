import type { AvatarClientParams } from '../../shared/api/types'

const MAX_TEXT = 2048
const MAX_URL = 4096

/**
 * Keep only short-lived, browser-safe runtime fields from the server response.
 * Vendor SDK secrets and unknown nested objects are intentionally discarded.
 */
export function normalizeClientParams(value: unknown): AvatarClientParams | undefined {
  if (!isRecord(value)) return undefined
  const top = pickParams(value)
  const nested = isRecord(value.realtime) ? pickParams(value.realtime) : undefined
  if (nested && Object.keys(nested).length) {
    const { realtime: _ignored, ...nestedValues } = nested
    top.realtime = nestedValues
  }
  return Object.keys(top).length ? top : undefined
}

function pickParams(source: Record<string, unknown>): AvatarClientParams {
  const result: AvatarClientParams = {}
  const endpoint = text(source.endpoint, MAX_URL)
  const wsUrl = text(source.wsUrl ?? source.ws_url, MAX_URL)
  const websocketUrl = text(source.websocketUrl ?? source.websocket_url, MAX_URL)
  const realtimeUrl = text(source.realtimeUrl ?? source.realtime_url, MAX_URL)
  const protocol = text(source.protocol, 64)
  const codec = text(source.codec, 64)
  const accessToken = text(source.accessToken ?? source.access_token, MAX_TEXT)
  const ticket = text(source.ticket, MAX_TEXT)
  const expiresAt = text(source.expiresAt ?? source.expires_at, 128)
  if (endpoint) result.endpoint = endpoint
  if (wsUrl) result.wsUrl = wsUrl
  if (websocketUrl) result.websocketUrl = websocketUrl
  if (realtimeUrl) result.realtimeUrl = realtimeUrl
  if (protocol) result.protocol = protocol
  if (codec) result.codec = codec
  if (accessToken) result.accessToken = accessToken
  if (ticket) result.ticket = ticket
  if (expiresAt) result.expiresAt = expiresAt
  const sampleRate = boundedNumber(source.sampleRate ?? source.sample_rate, 8_000, 96_000)
  const channels = boundedInteger(source.channels, 1, 2)
  const frameMs = boundedNumber(source.frameMs ?? source.frame_ms, 10, 100)
  const maxFrameBytes = boundedInteger(source.maxFrameBytes ?? source.max_frame_bytes, 320, 1_048_576)
  const heartbeatMs = boundedInteger(source.heartbeatMs ?? source.heartbeat_ms, 5_000, 300_000)
  if (sampleRate !== undefined) result.sampleRate = sampleRate
  if (channels !== undefined) result.channels = channels
  if (frameMs !== undefined) result.frameMs = frameMs
  if (maxFrameBytes !== undefined) result.maxFrameBytes = maxFrameBytes
  if (heartbeatMs !== undefined) result.heartbeatMs = heartbeatMs
  return result
}

function text(value: unknown, limit: number): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = value.trim()
  return normalized ? normalized.slice(0, limit) : undefined
}

function boundedNumber(value: unknown, min: number, max: number): number | undefined {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : NaN
  return Number.isFinite(parsed) && parsed >= min && parsed <= max ? parsed : undefined
}

function boundedInteger(value: unknown, min: number, max: number): number | undefined {
  const parsed = boundedNumber(value, min, max)
  return parsed !== undefined && Number.isInteger(parsed) ? parsed : undefined
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}
