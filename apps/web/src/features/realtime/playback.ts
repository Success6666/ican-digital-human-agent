import type { PcmPlaybackOptions, RealtimePlaybackState } from './types'

const DEFAULT_SAMPLE_RATE = 16_000
const DEFAULT_CHANNELS = 1 as const
const DEFAULT_MAX_QUEUE_MS = 2_000

/** Low-latency PCM16 queue. A generation token makes interrupt race-safe. */
export class Pcm16PlaybackQueue {
  private readonly sampleRate: number
  private readonly channels: 1 | 2
  private readonly maxQueueMs: number
  private readonly onState?: (state: RealtimePlaybackState) => void
  private readonly onDrop?: (count: number) => void
  private context: AudioContext | undefined
  private nextStart = 0
  private queuedMs = 0
  private generation = 0
  private active = new Set<AudioBufferSourceNode>()
  private closed = false

  constructor(options: PcmPlaybackOptions = {}) {
    this.sampleRate = clampInteger(options.sampleRate, DEFAULT_SAMPLE_RATE, 8_000, 96_000)
    this.channels = options.channels === 2 ? 2 : 1
    this.maxQueueMs = clampInteger(options.maxQueueMs, DEFAULT_MAX_QUEUE_MS, 200, 10_000)
    this.onState = options.onState
    this.onDrop = options.onDrop
  }

  get bufferedMs(): number { return Math.max(0, this.queuedMs) }

  async unlock(): Promise<void> {
    if (this.closed) return
    const context = this.ensureContext()
    await context.resume().catch(() => undefined)
  }

  enqueue(data: ArrayBuffer): boolean {
    if (this.closed || !data.byteLength || data.byteLength % (2 * this.channels) !== 0) {
      this.onDrop?.(1)
      return false
    }
    const frameCount = data.byteLength / (2 * this.channels)
    const durationMs = frameCount * 1000 / this.sampleRate
    if (durationMs <= 0 || durationMs > this.maxQueueMs || this.queuedMs + durationMs > this.maxQueueMs) {
      this.onDrop?.(1)
      return false
    }
    let context: AudioContext
    try {
      context = this.ensureContext()
    } catch {
      this.onDrop?.(1)
      this.notify('error')
      return false
    }
    const buffer = context.createBuffer(this.channels, frameCount, this.sampleRate)
    fillAudioBuffer(buffer, data, this.channels)
    const source = context.createBufferSource()
    source.buffer = buffer
    source.connect(context.destination)
    const generation = this.generation
    const now = context.currentTime
    const startAt = Math.max(now + 0.015, this.nextStart)
    this.nextStart = startAt + buffer.duration
    this.queuedMs = Math.max(0, (this.nextStart - now) * 1000)
    this.active.add(source)
    source.onended = () => {
      this.active.delete(source)
      if (generation !== this.generation) return
      this.queuedMs = Math.max(0, (this.nextStart - context.currentTime) * 1000)
      if (this.queuedMs <= 2) {
        this.queuedMs = 0
        this.nextStart = context.currentTime
        this.notify('idle')
      }
    }
    try {
      source.start(startAt)
      this.notify('playing')
      void context.resume().catch(() => this.notify('error'))
      return true
    } catch {
      this.active.delete(source)
      this.onDrop?.(1)
      this.notify('error')
      return false
    }
  }

  interrupt(): void {
    if (this.closed) return
    this.generation += 1
    for (const source of this.active) {
      try { source.stop() } catch { /* already ended */ }
      try { source.disconnect() } catch { /* best effort */ }
    }
    this.active.clear()
    this.queuedMs = 0
    if (this.context) this.nextStart = this.context.currentTime
    this.notify('interrupted')
  }

  async close(): Promise<void> {
    if (this.closed) return
    this.interrupt()
    this.closed = true
    const context = this.context
    if (context) await context.close().catch(() => undefined)
    this.context = undefined
  }

  private ensureContext(): AudioContext {
    if (this.context) return this.context
    const Constructor = getAudioContextConstructor()
    if (!Constructor) throw new Error('当前浏览器不支持音频播放')
    try {
      this.context = new Constructor({ sampleRate: this.sampleRate })
    } catch {
      this.context = new Constructor()
    }
    return this.context
  }

  private notify(state: RealtimePlaybackState): void { this.onState?.(state) }
}

function fillAudioBuffer(buffer: AudioBuffer, data: ArrayBuffer, channels: 1 | 2): void {
  const pcm = new DataView(data)
  const channelData = Array.from({ length: channels }, (_, index) => buffer.getChannelData(index))
  const frameCount = Math.floor(data.byteLength / (channels * 2))
  for (let frame = 0; frame < frameCount; frame += 1) {
    for (let channel = 0; channel < channels; channel += 1) {
      const offset = (frame * channels + channel) * 2
      const value = pcm.getInt16(offset, true)
      channelData[channel][frame] = value < 0 ? value / 0x8000 : value / 0x7fff
    }
  }
}

type AudioContextConstructor = new (options?: AudioContextOptions) => AudioContext

function getAudioContextConstructor(): AudioContextConstructor | undefined {
  if (typeof window === 'undefined') return undefined
  const candidate = window.AudioContext ?? (window as Window & { webkitAudioContext?: AudioContextConstructor }).webkitAudioContext
  return candidate as AudioContextConstructor | undefined
}

function clampInteger(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isInteger(parsed) && parsed >= min && parsed <= max ? parsed : fallback
}
