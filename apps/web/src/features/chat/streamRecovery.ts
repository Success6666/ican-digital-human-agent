export interface StreamRecoveryState {
  /** SSE 是否已经收到 start/filler/intent/tool/delta 等业务事件。 */
  executionStarted: boolean
  /** 是否收到 done/interrupted，表示服务端已给出终态。 */
  terminal: boolean
  /** 是否由用户主动停止。 */
  aborted: boolean
}

export type StreamFailureAction = 'fallback' | 'recoverable' | 'stopped' | 'completed'

/**
 * Decide how a stream failure should be handled without coupling the UI to fetch.
 * Once execution has started, retrying POST /chat may duplicate side effects.
 */
export function streamFailureAction(state: StreamRecoveryState): StreamFailureAction {
  if (state.aborted) return 'stopped'
  if (state.terminal) return 'completed'
  return state.executionStarted ? 'recoverable' : 'fallback'
}

export function markBusinessEvent(kind: string): boolean {
  return kind !== 'error'
}

export function recoverableStreamMessage(hasPartialReply: boolean): string {
  return hasPartialReply
    ? '流式响应中断，已保留部分结果，可重试。'
    : '流式响应中断，可重试。'
}
