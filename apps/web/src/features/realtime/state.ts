import { sanitizeDisplayText } from '../../shared/lib/format'
import type { RealtimeAction, RealtimeInboundEvent, RealtimePhase, RealtimeState } from './types'
import { initialRealtimeState } from './types'

const phaseLabels: Record<RealtimePhase, string> = {
  idle: '实时语音待命',
  listening: '正在聆听',
  thinking: '正在理解',
  speaking: '数字人正在表达',
  interrupting: '正在停止上一轮',
  degraded: '语音能力暂不可用',
  error: '实时通道异常',
}

export function realtimeReducer(state: RealtimeState, action: RealtimeAction): RealtimeState {
  switch (action.type) {
    case 'reset':
      return {
        ...initialRealtimeState,
        sessionId: action.sessionId,
        textSupported: action.textSupported ?? action.supported,
        audioSupported: action.supported,
        connection: (action.textSupported ?? action.supported) ? 'idle' : 'unsupported',
        phase: action.supported ? 'idle' : 'degraded',
        statusText: action.supported ? phaseLabels.idle : action.textSupported ? '文本实时可用，当前未配置语音输入' : '当前仅支持文本实时链路',
      }
    case 'connection':
      return {
        ...state,
        connection: action.state,
        connectionId: action.connectionId ?? state.connectionId,
        statusText: action.message ?? connectionText(action.state),
        error: action.state === 'error' ? state.error : undefined,
        phase: action.state === 'error' ? 'error' : state.phase,
        lastEventAt: new Date().toISOString(),
      }
    case 'recording':
      return {
        ...state,
        recording: action.state,
        statusText: action.message ?? recordingText(action.state),
        phase: action.state === 'recording' ? 'listening' : state.phase,
        error: action.state === 'error' || action.state === 'unsupported' ? action.message : state.error,
        lastEventAt: new Date().toISOString(),
      }
    case 'capabilities':
      return {
        ...state,
        audioSupported: action.audioInput ?? state.audioSupported,
        audioOutputSupported: action.audioOutput ?? state.audioOutputSupported,
        asrStatus: capabilityStatus(action.asr),
        ttsStatus: capabilityStatus(action.tts),
        statusText: capabilityMessage(action),
        lastEventAt: new Date().toISOString(),
      }
    case 'playback':
      return {
        ...state,
        playback: action.state,
        statusText: action.message ?? playbackText(action.state),
        phase: action.state === 'playing' ? 'speaking' : action.state === 'interrupted' ? 'idle' : state.phase,
        lastEventAt: new Date().toISOString(),
      }
    case 'phase':
      return {
        ...state,
        phase: action.phase,
        statusText: action.message ?? phaseLabels[action.phase],
        lastEventAt: new Date().toISOString(),
      }
    case 'revision':
      return {
        ...state,
        utteranceId: action.utteranceId ?? state.utteranceId,
        revision: action.revision,
        runId: undefined,
        interimTranscript: '',
        transcript: '',
        assistantText: '',
        error: undefined,
        lastEventAt: new Date().toISOString(),
      }
    case 'run':
      return { ...state, runId: action.runId, phase: action.runId ? 'thinking' : state.phase, lastEventAt: new Date().toISOString() }
    case 'transcript':
      if (action.status === 'unsupported') {
        return { ...state, phase: 'degraded', statusText: '当前未配置语音识别，请使用文本输入', error: undefined, lastEventAt: new Date().toISOString() }
      }
      if (action.status === 'partial') {
        return { ...state, interimTranscript: sanitizeDisplayText(action.text ?? '', 400), phase: 'listening', statusText: '正在聆听', lastEventAt: new Date().toISOString() }
      }
      return { ...state, transcript: sanitizeDisplayText(action.text ?? '', 400), interimTranscript: '', phase: 'thinking', statusText: '正在理解', lastEventAt: new Date().toISOString() }
    case 'assistant':
      return {
        ...state,
        assistantText: action.append ? `${state.assistantText}${action.text}` : action.text,
        phase: 'speaking',
        statusText: '数字人正在表达',
        lastEventAt: new Date().toISOString(),
      }
    case 'buffer':
      return { ...state, bufferedBytes: Math.max(0, action.bytes), droppedFrames: state.droppedFrames + Math.max(0, action.dropped ?? 0), lastEventAt: new Date().toISOString() }
    case 'audio_level':
      return { ...state, audioLevel: Math.max(0, Math.min(1, action.level)), lastEventAt: new Date().toISOString() }
    case 'error':
      return { ...state, connection: action.fatal ? 'error' : state.connection, phase: 'error', statusText: sanitizeDisplayText(action.message, 180), error: sanitizeDisplayText(action.message, 180), lastEventAt: new Date().toISOString() }
    case 'event':
      return { ...state, lastEventAt: action.at ?? new Date().toISOString() }
    default:
      return state
  }
}

export function phaseForInbound(event: RealtimeInboundEvent): RealtimePhase | undefined {
  const explicit = String(event.phase ?? '').toLowerCase()
  if (explicit === 'listening' || explicit === 'thinking' || explicit === 'speaking' || explicit === 'interrupting' || explicit === 'degraded' || explicit === 'idle') return explicit
  const type = String(event.type ?? '').toLowerCase()
  if (type === 'start' || type === 'run_started' || type === 'intent' || type === 'tool_disclosure' || type === 'rag' || type === 'tool') return 'thinking'
  if (type === 'delta' || type === 'provider' || type === 'audio_queue') return 'speaking'
  if (type === 'interrupted' || type === 'run_done' || type === 'done') return 'idle'
  return undefined
}

export function isStaleInbound(state: RealtimeState, event: RealtimeInboundEvent): boolean {
  if (event.sessionId && state.sessionId && event.sessionId !== state.sessionId) return true
  if (event.revision !== undefined && event.revision < state.revision) return true
  if (event.utteranceId && state.utteranceId && event.utteranceId !== state.utteranceId) return true
  if (event.runId && state.runId && event.runId !== state.runId && ['audio_queue', 'delta', 'provider', 'interrupted', 'run_done', 'done'].includes(String(event.type).toLowerCase())) return true
  return false
}

function connectionText(state: RealtimeState['connection']): string {
  if (state === 'connecting') return '正在连接实时通道'
  if (state === 'reconnecting') return '实时通道正在恢复'
  if (state === 'connected') return '实时通道已连接'
  if (state === 'closed') return '实时通道已关闭'
  if (state === 'unsupported') return '当前仅支持文本实时链路'
  if (state === 'error') return '实时通道异常'
  return phaseLabels.idle
}

function recordingText(state: RealtimeState['recording']): string {
  if (state === 'requesting') return '正在申请麦克风权限'
  if (state === 'recording') return '正在聆听，可随时改口'
  if (state === 'stopping') return '正在结束录音'
  if (state === 'unsupported') return '当前浏览器不支持实时录音'
  if (state === 'error') return '麦克风暂不可用'
  return phaseLabels.idle
}

function playbackText(state: RealtimeState['playback']): string {
  if (state === 'playing') return '数字人正在表达'
  if (state === 'interrupted') return '已停止播放'
  if (state === 'error') return '音频播放暂不可用'
  return phaseLabels.idle
}

function capabilityStatus(value: unknown): RealtimeState['asrStatus'] {
  if (value === true || value === 'supported' || value === 'ready' || value === 'available') return 'supported'
  if (value === false || value === 'unsupported' || value === 'unavailable' || value === 'disabled') return 'unsupported'
  return 'unknown'
}

function capabilityMessage(action: Extract<RealtimeAction, { type: 'capabilities' }>): string {
  if (capabilityStatus(action.asr) === 'unsupported') return '实时通道已连接，语音识别未配置'
  if (action.audioInput === false) return '实时通道已连接，当前未配置语音输入'
  return '实时通道已连接'
}
