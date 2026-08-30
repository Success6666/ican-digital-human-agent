import type { AvatarClientParams } from '../../../shared/api/types'

export interface AvatarRuntimeStatus {
  phase: 'loading' | 'ready' | 'speaking' | 'error'
  progress?: number
  message?: string
}

export interface BrowserAvatarRuntime {
  connect(host: HTMLElement, params: AvatarClientParams, onStatus: (status: AvatarRuntimeStatus) => void): Promise<void>
  speak(text: string): Promise<void>
  interrupt(): Promise<void>
  dispose(): Promise<void>
}
