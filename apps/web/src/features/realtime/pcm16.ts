import type { PcmRecorderOptions } from './types'

const DEFAULT_SAMPLE_RATE = 16_000
const DEFAULT_CHANNELS = 1 as const
const DEFAULT_FRAME_MS = 20
const DEFAULT_MAX_PENDING_BYTES = 512 * 1024

type AudioContextConstructor = new (options?: AudioContextOptions) => AudioContext

/** Convert browser float samples to signed little-endian PCM16. */
export function floatToPcm16(samples: Float32Array, channels: 1 | 2 = DEFAULT_CHANNELS): ArrayBuffer {
  const output = new ArrayBuffer(samples.length * channels * 2)
  const view = new DataView(output)
  for (let index = 0; index < samples.length; index += 1) {
    const value = Math.max(-1, Math.min(1, samples[index] ?? 0))
    const pcm = value < 0 ? Math.round(value * 0x8000) : Math.round(value * 0x7fff)
    for (let channel = 0; channel < channels; channel += 1) view.setInt16((index * channels + channel) * 2, pcm, true)
  }
  return output
}

/** Downmix an interleaved input buffer without retaining device-specific channels. */
export function downmixToMono(input: Float32Array, channels: number): Float32Array {
  const count = Math.max(1, Math.floor(channels))
  if (count === 1) return input
  const frames = Math.floor(input.length / count)
  const output = new Float32Array(frames)
  for (let frame = 0; frame < frames; frame += 1) {
    let sum = 0
    for (let channel = 0; channel < count; channel += 1) sum += input[frame * count + channel] ?? 0
    output[frame] = sum / count
  }
  return output
}

/** Stateless linear resampling helper used by tests and diagnostics. */
export function resampleLinear(input: Float32Array, sourceRate: number, targetRate: number): Float32Array {
  if (!input.length || sourceRate <= 0 || targetRate <= 0 || sourceRate === targetRate) return input
  const length = Math.max(1, Math.round(input.length * targetRate / sourceRate))
  const output = new Float32Array(length)
  const ratio = sourceRate / targetRate
  for (let index = 0; index < length; index += 1) {
    const position = index * ratio
    const left = Math.min(input.length - 1, Math.floor(position))
    const right = Math.min(input.length - 1, left + 1)
    const fraction = position - left
    output[index] = (input[left] ?? 0) * (1 - fraction) + (input[right] ?? 0) * fraction
  }
  return output
}

export function pcmFrameBytes(sampleRate = DEFAULT_SAMPLE_RATE, frameMs = DEFAULT_FRAME_MS, channels: 1 | 2 = DEFAULT_CHANNELS): number {
  return Math.max(2, Math.round(sampleRate * frameMs / 1000) * channels * 2)
}

/** Browser microphone capture with bounded PCM16 frames and deterministic cleanup. */
export class Pcm16Recorder {
  private readonly options: Required<Pick<PcmRecorderOptions, 'onChunk'>> & PcmRecorderOptions
  private readonly sampleRate: number
  private readonly channels: 1 | 2
  private readonly frameBytes: number
  private readonly maxPendingBytes: number
  private stream: MediaStream | undefined
  private context: AudioContext | undefined
  private source: MediaStreamAudioSourceNode | undefined
  private processor: ScriptProcessorNode | undefined
  private sink: GainNode | undefined
  private pending = new Uint8Array(0)
  private resampler: StreamingResampler | undefined
  private started = false

  constructor(options: PcmRecorderOptions) {
    this.options = options
    this.sampleRate = clampInteger(options.sampleRate, DEFAULT_SAMPLE_RATE, 8_000, 96_000)
    this.channels = options.channels === 2 ? 2 : 1
    this.frameBytes = pcmFrameBytes(this.sampleRate, clampNumber(options.frameMs, DEFAULT_FRAME_MS, 10, 100), this.channels)
    this.maxPendingBytes = Math.max(this.frameBytes, clampInteger(options.maxPendingBytes, DEFAULT_MAX_PENDING_BYTES, this.frameBytes, 4 * 1024 * 1024))
  }

  static get supported(): boolean {
    return typeof navigator !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia) && Boolean(getAudioContextConstructor())
  }

  get isRecording(): boolean { return this.started }

  async start(): Promise<void> {
    if (this.started) return
    if (!Pcm16Recorder.supported) throw new Error('当前浏览器不支持实时录音')
    let stream: MediaStream | undefined
    let context: AudioContext | undefined
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: this.channels, echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false })
      const Constructor = getAudioContextConstructor()
      if (!Constructor) throw new Error('当前浏览器不支持音频采集')
      context = new Constructor({ sampleRate: this.sampleRate })
      await context.resume().catch(() => undefined)
      const source = context.createMediaStreamSource(stream)
      const processor = context.createScriptProcessor(2048, 1, 1)
      const sink = context.createGain()
      sink.gain.value = 0
      processor.onaudioprocess = (event) => this.handleInput(event.inputBuffer)
      source.connect(processor)
      processor.connect(sink)
      sink.connect(context.destination)
      this.stream = stream
      this.context = context
      this.source = source
      this.processor = processor
      this.sink = sink
      this.resampler = new StreamingResampler(context.sampleRate, this.sampleRate)
      this.pending = new Uint8Array(0)
      this.started = true
    } catch (cause) {
      stream?.getTracks().forEach((track) => track.stop())
      await context?.close().catch(() => undefined)
      if (cause instanceof Error && cause.message) throw cause
      throw new Error('麦克风权限未授予或设备暂不可用')
    }
  }

  async stop(): Promise<void> {
    this.started = false
    if (this.processor) this.processor.onaudioprocess = null
    this.source?.disconnect()
    this.processor?.disconnect()
    this.sink?.disconnect()
    this.stream?.getTracks().forEach((track) => track.stop())
    await this.context?.close().catch(() => undefined)
    this.stream = undefined
    this.context = undefined
    this.source = undefined
    this.processor = undefined
    this.sink = undefined
    this.resampler = undefined
    this.pending = new Uint8Array(0)
  }

  private handleInput(buffer: AudioBuffer): void {
    if (!this.started || !this.resampler) return
    const channels = Math.max(1, buffer.numberOfChannels)
    const input = new Float32Array(buffer.length * channels)
    for (let channel = 0; channel < channels; channel += 1) {
      const values = buffer.getChannelData(channel)
      for (let frame = 0; frame < buffer.length; frame += 1) input[frame * channels + channel] = values[frame] ?? 0
    }
    const resampled = this.resampler.push(downmixToMono(input, channels))
    if (!resampled.length) return
    this.appendPcm(floatToPcm16(resampled, this.channels))
  }

  private appendPcm(chunk: ArrayBuffer): void {
    const bytes = new Uint8Array(chunk)
    const merged = new Uint8Array(this.pending.length + bytes.length)
    merged.set(this.pending)
    merged.set(bytes, this.pending.length)
    this.pending = merged
    let dropped = 0
    if (this.pending.length > this.maxPendingBytes) {
      const overflow = this.pending.length - this.maxPendingBytes
      const discard = Math.min(this.pending.length, overflow - (overflow % this.frameBytes) + this.frameBytes)
      this.pending = this.pending.slice(discard)
      dropped = Math.max(1, Math.floor(discard / this.frameBytes))
      this.options.onDrop?.(dropped)
    }
    while (this.pending.length >= this.frameBytes) {
      const frame = this.pending.slice(0, this.frameBytes)
      this.pending = this.pending.slice(this.frameBytes)
      if (this.options.onChunk(frame.buffer) === false) {
        dropped += 1
        this.options.onDrop?.(1)
      }
    }
    if (dropped > 0 && this.pending.length > this.maxPendingBytes) this.pending = this.pending.slice(-this.maxPendingBytes)
  }
}

class StreamingResampler {
  private source = new Float32Array(0)
  private position = 0
  private readonly ratio: number

  constructor(private readonly sourceRate: number, private readonly targetRate: number) {
    this.ratio = sourceRate / targetRate
  }

  push(input: Float32Array): Float32Array {
    if (!input.length) return new Float32Array(0)
    if (this.sourceRate === this.targetRate) return input
    const merged = new Float32Array(this.source.length + input.length)
    merged.set(this.source)
    merged.set(input, this.source.length)
    this.source = merged
    const output: number[] = []
    while (this.position + 1 < this.source.length) {
      const left = Math.floor(this.position)
      const right = Math.min(this.source.length - 1, left + 1)
      const fraction = this.position - left
      output.push((this.source[left] ?? 0) * (1 - fraction) + (this.source[right] ?? 0) * fraction)
      this.position += this.ratio
    }
    const consumed = Math.max(0, Math.floor(this.position) - 1)
    if (consumed > 0) {
      this.source = this.source.slice(consumed)
      this.position -= consumed
    }
    return Float32Array.from(output)
  }
}

function getAudioContextConstructor(): AudioContextConstructor | undefined {
  if (typeof window === 'undefined') return undefined
  const candidate = window.AudioContext ?? (window as Window & { webkitAudioContext?: AudioContextConstructor }).webkitAudioContext
  return candidate as AudioContextConstructor | undefined
}

function clampNumber(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) && parsed >= min && parsed <= max ? parsed : fallback
}

function clampInteger(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = clampNumber(value, fallback, min, max)
  return Number.isInteger(parsed) ? parsed : fallback
}
