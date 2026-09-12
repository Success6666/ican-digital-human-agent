import { RealtimeEventGate } from './eventGate'
import type { Pcm16PlaybackQueue } from './playback'
import type { RealtimeAction, RealtimeInboundEvent } from './types'

type Dispatch = (action: RealtimeAction) => void

export interface RealtimeEventContext {
  gate: RealtimeEventGate
  playback?: Pcm16PlaybackQueue
  dispatch: Dispatch
  stopRecording: () => Promise<void>
  readTranscript: (text: string) => void
  readAssistant: (text: string, append: boolean) => void
  revision: number
  utteranceId?: string
  setRevision: (revision: number) => void
  setUtteranceId: (utteranceId: string) => void
  setUtteranceOpen: (open: boolean) => void
  setRunId: (runId?: string) => void
  disposed: boolean
}

/** Apply only current-generation events to the readable realtime state. */
export function handleRealtimeEvent(event: RealtimeInboundEvent, context: RealtimeEventContext): void {
  const kind = String(event.type ?? '').toLowerCase()
  const accepted = context.gate.accept(event)
  if (!accepted || context.disposed) return
  const revisionChanged = accepted.revision !== undefined && accepted.revision > context.revision
  const generationUtteranceId = accepted.utteranceId ?? context.gate.currentUtteranceId ?? context.utteranceId
  if (revisionChanged) {
    context.setRevision(accepted.revision as number)
    if (generationUtteranceId && generationUtteranceId !== context.utteranceId) context.setUtteranceId(generationUtteranceId)
    context.setRunId(undefined)
    context.setUtteranceOpen(false)
    context.playback?.interrupt()
    context.dispatch({ type: 'revision', utteranceId: generationUtteranceId, revision: accepted.revision as number })
  } else if (accepted.utteranceId && accepted.utteranceId !== context.utteranceId) {
    context.setUtteranceId(accepted.utteranceId)
  }
  if (kind === 'run_started') {
    context.setRunId(event.runId)
    context.gate.setRun(event.runId)
  } else if (kind === 'transcript') {
    const status = event.status === 'partial' || event.status === 'unsupported' || event.status === 'error' ? event.status : 'final'
    context.dispatch({ type: 'transcript', status, text: event.text, reason: event.reason })
    context.setUtteranceOpen(status === 'partial')
    if (status === 'final' && event.text) context.readTranscript(event.text)
  } else if (kind === 'delta' || kind === 'message' || kind === 'assistant') {
    if (event.text) {
      const append = kind !== 'assistant'
      context.dispatch({ type: 'assistant', text: event.text, append })
      context.readAssistant(event.text, append)
    }
  } else if (kind === 'audio_queue') {
    if (event.data) context.playback?.enqueue(event.data)
    // `droppedFrames` is what turns a silent truncation into a visible one, so it
    // must actually reach the state: the server has always sent it, the panel has
    // always rendered it, and the event handler simply never forwarded it, which
    // left the "已丢弃 N 帧" badge pinned at zero no matter what the server did.
    context.dispatch({
      type: 'buffer',
      bytes: event.bufferedBytes ?? 0,
      dropped: event.droppedFrames ?? 0,
      capacity: event.capacityBytes ?? 0,
    })
  } else if (kind === 'ack') {
    if (event.action === 'interrupt' && event.accepted) context.dispatch({ type: 'phase', phase: 'idle', message: '上一轮已停止' })
    if (event.action === 'audio_start' && event.accepted === false) {
      context.dispatch({ type: 'error', message: event.reason ?? '录音未被实时通道接受' })
      void context.stopRecording()
    }
  } else if (kind === 'interrupted' || kind === 'run_done' || kind === 'done') {
    if (kind === 'interrupted') context.playback?.interrupt()
    context.gate.markRunTerminal(accepted.runId)
    context.setRunId(undefined)
    context.dispatch({ type: 'run', runId: undefined })
    context.dispatch({ type: 'phase', phase: 'idle', message: kind === 'interrupted' ? '上一轮已停止' : '实时语音待命' })
  } else if (kind === 'error') {
    context.dispatch({ type: 'error', message: event.message ?? '实时通道返回错误' })
  }
}
