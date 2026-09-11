import type { AvatarClientParams } from '../../../shared/api/types'
import type { AvatarPerformanceCue } from '../../../shared/api/types'

export interface AvatarRuntimeStatus {
  phase: 'loading' | 'ready' | 'speaking' | 'warning' | 'error'
  progress?: number
  message?: string
}

/**
 * Trace handle for the vendor avatar SDK.
 *
 * The SDK is the only place that knows whether a speak request actually reached
 * TTSA, so its lifecycle is reported onto the same trace as the rest of the
 * voice loop. `traceId` is read lazily because the browser learns it from the
 * realtime handshake, which can complete after the avatar runtime is created.
 */
export interface AvatarTraceContext {
  traceId(): string | undefined
  runId(): string | undefined
  utteranceId(): string | undefined
  revision(): number | undefined
}

export interface BrowserAvatarRuntime {
  connect(host: HTMLElement, params: AvatarClientParams, onStatus: (status: AvatarRuntimeStatus) => void): Promise<void>
  setVisibility(visible: boolean): void
  speak(text: string, presentation?: AvatarPerformanceCue, options?: { flush?: boolean }): Promise<void>
  interrupt(): Promise<void>
  dispose(): Promise<void>
  setTraceContext?(context: AvatarTraceContext): void
}
