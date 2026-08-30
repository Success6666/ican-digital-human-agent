import { useCallback, useEffect, useReducer, useRef } from 'react'
import type { AvatarSession } from '../../shared/api/types'
import { RealtimeRuntime } from './runtime'
import { realtimeReducer } from './state'
import { initialRealtimeState, type RealtimeSessionOptions, type RealtimeState } from './types'

export interface RealtimeController {
  state: RealtimeState
  supported: boolean
  textSupported: boolean
  connect: () => Promise<boolean>
  disconnect: () => Promise<void>
  startRecording: () => Promise<boolean>
  stopRecording: () => Promise<void>
  interrupt: (reason?: string) => Promise<void>
  toggleRecording: () => Promise<boolean>
  sendText: (text: string, isFinal?: boolean) => boolean
}

/** React binding for the transport-agnostic realtime runtime. */
export function useRealtimeSession(
  session: AvatarSession | null,
  options: RealtimeSessionOptions = {},
): RealtimeController {
  const [state, dispatch] = useReducer(realtimeReducer, initialRealtimeState)
  const stateRef = useRef(state)
  const optionsRef = useRef(options)
  const runtimeRef = useRef<RealtimeRuntime | undefined>(undefined)

  useEffect(() => { stateRef.current = state }, [state])
  useEffect(() => { optionsRef.current = options }, [options])

  useEffect(() => {
    const runtime = new RealtimeRuntime(session, dispatch, () => optionsRef.current)
    runtimeRef.current = runtime
    dispatch({ type: 'reset', sessionId: session?.sessionId, supported: runtime.supported, textSupported: runtime.textSupported })
    runtime.mount(session)
    return () => {
      if (runtimeRef.current === runtime) runtimeRef.current = undefined
      void runtime.dispose()
    }
  }, [session?.sessionId])

  const connect = useCallback(async () => runtimeRef.current?.connect() ?? false, [])
  const disconnect = useCallback(async () => runtimeRef.current?.disconnect(), [])
  const startRecording = useCallback(async () => runtimeRef.current?.startRecording() ?? false, [])
  const stopRecording = useCallback(async () => runtimeRef.current?.stopRecording(), [])
  const interrupt = useCallback(async (reason?: string) => runtimeRef.current?.interrupt(reason), [])
  const toggleRecording = useCallback(async () => {
    const runtime = runtimeRef.current
    if (!runtime) return false
    if (stateRef.current.recording === 'recording' || stateRef.current.recording === 'requesting') {
      await runtime.stopRecording()
      return false
    }
    return runtime.startRecording()
  }, [])
  const sendText = useCallback((text: string, isFinal = true) => runtimeRef.current?.sendText(text, isFinal) ?? false, [])

  return {
    state,
    supported: runtimeRef.current?.supported ?? false,
    textSupported: runtimeRef.current?.textSupported ?? false,
    connect,
    disconnect,
    startRecording,
    stopRecording,
    interrupt,
    toggleRecording,
    sendText,
  }
}
