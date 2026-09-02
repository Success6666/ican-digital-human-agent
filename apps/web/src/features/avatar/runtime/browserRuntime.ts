import type { AvatarClientParams } from '../../../shared/api/types'
import type { AvatarPerformanceCue } from '../../../shared/api/types'

export interface AvatarRuntimeStatus {
  phase: 'loading' | 'ready' | 'speaking' | 'error'
  progress?: number
  message?: string
}

export interface BrowserAvatarRuntime {
  connect(host: HTMLElement, params: AvatarClientParams, onStatus: (status: AvatarRuntimeStatus) => void): Promise<void>
  setVisibility(visible: boolean): void
  speak(text: string, presentation?: AvatarPerformanceCue, options?: { flush?: boolean }): Promise<void>
  interrupt(): Promise<void>
  dispose(): Promise<void>
}
