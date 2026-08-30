import type { ChatMessage } from './model'

type Commit = (messageId: string, patch: Partial<ChatMessage>) => void

/** Coalesce high-frequency stream deltas into one paint-sized update. */
export class AssistantDeltaBatcher {
  private readonly pending = new Map<string, Partial<ChatMessage>>()
  private timer: ReturnType<typeof setTimeout> | undefined

  constructor(private readonly commit: Commit, private readonly intervalMs = 32) {}

  enqueue(messageId: string, patch: Partial<ChatMessage>): void {
    this.pending.set(messageId, patch)
    if (this.timer === undefined) this.timer = setTimeout(() => this.flush(), this.intervalMs)
  }

  flush(): void {
    if (this.timer !== undefined) clearTimeout(this.timer)
    this.timer = undefined
    if (!this.pending.size) return
    const updates = [...this.pending.entries()]
    this.pending.clear()
    for (const [messageId, patch] of updates) this.commit(messageId, patch)
  }

  cancel(): void {
    if (this.timer !== undefined) clearTimeout(this.timer)
    this.timer = undefined
    this.pending.clear()
  }
}
