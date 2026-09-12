import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'
import * as ts from 'typescript'

async function loadTsModule(relativePath) {
  const sourcePath = fileURLToPath(new URL(relativePath, import.meta.url))
  const source = await readFile(sourcePath, 'utf8')
  const output = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
  }).outputText
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(output).toString('base64')}`
  return import(moduleUrl)
}

const { decideAudioEnd } = await loadTsModule('../src/features/realtime/audioLifecycle.ts')

async function loadStateModule() {
  const typesPath = fileURLToPath(new URL('../src/features/realtime/types.ts', import.meta.url))
  const statePath = fileURLToPath(new URL('../src/features/realtime/state.ts', import.meta.url))
  const typesOutput = ts.transpileModule(await readFile(typesPath, 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
  }).outputText
  const typesModule = { exports: {} }
  vm.runInNewContext(typesOutput, { module: typesModule, exports: typesModule.exports })
  const stateOutput = ts.transpileModule(await readFile(statePath, 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
  }).outputText
  const stateModule = { exports: {} }
  vm.runInNewContext(stateOutput, {
    module: stateModule,
    exports: stateModule.exports,
    Date,
    require(specifier) {
      if (specifier === './types') return typesModule.exports
      if (specifier === '../../shared/lib/format') return { sanitizeDisplayText: (value) => String(value) }
      throw new Error(`unexpected import: ${specifier}`)
    },
  })
  return stateModule.exports
}

test('audio_end clears the active generation even when transport is unavailable', () => {
  const active = { utteranceId: 'utt-1', revision: 3 }
  assert.deepEqual(decideAudioEnd(active, active, false), { accepted: true, shouldSend: false })
})

test('audio_end cannot close a different generation', () => {
  const active = { utteranceId: 'utt-1', revision: 3 }
  assert.deepEqual(decideAudioEnd(active, { utteranceId: 'utt-2', revision: 3 }, true), { accepted: false, shouldSend: false })
  assert.deepEqual(decideAudioEnd(active, { utteranceId: 'utt-1', revision: 4 }, true), { accepted: false, shouldSend: false })
})

test('Mofa audio capability unlocks the realtime microphone transport', async () => {
  const { capabilityNames } = await loadTsModule('../src/features/avatar/capabilities.ts')
  const { hasAudioInput } = await loadTsModule('../src/features/realtime/types.ts')
  const capabilities = capabilityNames({ audio_input: true })
  assert.deepEqual(capabilities, ['语音输入'])
  assert.equal(hasAudioInput({ capabilities }), true)
})

test('recorder reuses the granted microphone session across continuous turns', async () => {
  const { Pcm16Recorder } = await loadTsModule('../src/features/realtime/pcm16.ts')
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  let requests = 0
  let stopped = 0

  class FakeAudioContext {
    constructor(options = {}) {
      this.sampleRate = options.sampleRate ?? 16_000
      this.state = 'suspended'
      this.destination = {}
    }

    async resume() { this.state = 'running' }
    async close() { this.state = 'closed' }
    createMediaStreamSource() { return { connect() {}, disconnect() {} } }
    createScriptProcessor() { return { connect() {}, disconnect() {}, onaudioprocess: null } }
    createGain() { return { gain: { value: 1 }, connect() {}, disconnect() {} } }
  }

  const track = { readyState: 'live', stop: () => { stopped += 1 } }
  const stream = { active: true, getAudioTracks: () => [track], getTracks: () => [track] }
  Object.defineProperty(globalThis, 'window', { configurable: true, value: { AudioContext: FakeAudioContext } })
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: { mediaDevices: { getUserMedia: async () => { requests += 1; return stream } } },
  })
  try {
    const recorder = new Pcm16Recorder({ onChunk: () => true })
    await Promise.all([recorder.start(), recorder.start()])
    recorder.pause()
    await recorder.start()
    assert.equal(requests, 1)
    assert.equal(recorder.isRecording, true)
    await recorder.stop()
    assert.equal(stopped, 1)
  } finally {
    if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow)
    else Reflect.deleteProperty(globalThis, 'window')
    if (originalNavigator) Object.defineProperty(globalThis, 'navigator', originalNavigator)
    else Reflect.deleteProperty(globalThis, 'navigator')
  }
})

test('recorder cleans a microphone stream that resolves after cancellation', async () => {
  const { Pcm16Recorder } = await loadTsModule('../src/features/realtime/pcm16.ts')
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  let resolveStream
  let stopped = 0
  const stream = {
    active: true,
    getAudioTracks: () => [{ readyState: 'live', stop: () => { stopped += 1 } }],
    getTracks: () => [{ readyState: 'live', stop: () => { stopped += 1 } }],
  }

  class FakeAudioContext {
    constructor() { this.sampleRate = 16_000; this.state = 'suspended'; this.destination = {} }
    async resume() { this.state = 'running' }
    async close() { this.state = 'closed' }
    createMediaStreamSource() { return { connect() {}, disconnect() {} } }
    createScriptProcessor() { return { connect() {}, disconnect() {}, onaudioprocess: null } }
    createGain() { return { gain: { value: 1 }, connect() {}, disconnect() {} } }
  }

  Object.defineProperty(globalThis, 'window', { configurable: true, value: { AudioContext: FakeAudioContext } })
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: { mediaDevices: { getUserMedia: () => new Promise((resolve) => { resolveStream = resolve }) } },
  })
  try {
    const recorder = new Pcm16Recorder({ onChunk: () => true })
    const starting = recorder.start()
    await Promise.resolve()
    await recorder.stop()
    resolveStream(stream)
    await assert.rejects(starting, /录音已取消/)
    assert.equal(stopped, 1)
    assert.equal(recorder.isRecording, false)
  } finally {
    if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow)
    else Reflect.deleteProperty(globalThis, 'window')
    if (originalNavigator) Object.defineProperty(globalThis, 'navigator', originalNavigator)
    else Reflect.deleteProperty(globalThis, 'navigator')
  }
})

test('recorder reacquires a microphone stream after its prior track ends', async () => {
  const { Pcm16Recorder } = await loadTsModule('../src/features/realtime/pcm16.ts')
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  let requests = 0
  const firstTrack = { readyState: 'live', stop() { this.readyState = 'ended' } }
  const firstStream = { active: true, getAudioTracks: () => [firstTrack], getTracks: () => [firstTrack] }
  const secondTrack = { readyState: 'live', stop() { this.readyState = 'ended' } }
  const secondStream = { active: true, getAudioTracks: () => [secondTrack], getTracks: () => [secondTrack] }

  class FakeAudioContext {
    constructor(options = {}) { this.sampleRate = options.sampleRate ?? 16_000; this.state = 'suspended'; this.destination = {} }
    async resume() { this.state = 'running' }
    async close() { this.state = 'closed' }
    createMediaStreamSource() { return { connect() {}, disconnect() {} } }
    createScriptProcessor() { return { connect() {}, disconnect() {}, onaudioprocess: null } }
    createGain() { return { gain: { value: 1 }, connect() {}, disconnect() {} } }
  }

  Object.defineProperty(globalThis, 'window', { configurable: true, value: { AudioContext: FakeAudioContext } })
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: { mediaDevices: { getUserMedia: async () => (++requests === 1 ? firstStream : secondStream) } },
  })
  try {
    const recorder = new Pcm16Recorder({ onChunk: () => true })
    await recorder.start()
    recorder.pause()
    firstTrack.readyState = 'ended'
    firstStream.active = false
    await recorder.start()
    assert.equal(requests, 2)
    await recorder.stop()
  } finally {
    if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow)
    else Reflect.deleteProperty(globalThis, 'window')
    if (originalNavigator) Object.defineProperty(globalThis, 'navigator', originalNavigator)
    else Reflect.deleteProperty(globalThis, 'navigator')
  }
})

test('ASR errors remain visible without exposing raw backend details', async () => {
  const { initialRealtimeState, realtimeReducer } = await loadStateModule()
  const next = realtimeReducer(initialRealtimeState, { type: 'transcript', status: 'error', reason: 'asr_http_502' })
  assert.equal(next.phase, 'error')
  assert.equal(next.statusText, '语音识别服务返回异常，请重试')
  assert.equal(next.error, '语音识别服务返回异常，请重试')
})

test('the recorder backlog is not sized by the server utterance budget', async () => {
  // `maxAudioBufferBytes` is how much audio the *server* may retain for one
  // utterance; it is not a transport budget. Wiring it into the recorder made the
  // backlog of unsent audio scale with the server, so a stalled socket could hold
  // a minute of already-spoken audio and deliver it long after the user stopped
  // talking. Raising the server budget to cover long questions must therefore not
  // loosen the transport bound, and the two must stay independent.
  const runtime = await readFile(fileURLToPath(new URL('../src/features/realtime/runtime.ts', import.meta.url)), 'utf8')
  assert.doesNotMatch(runtime, /maxPendingBytes:\s*config\.maxAudioBufferBytes/)
  assert.doesNotMatch(runtime, /RecorderConfig[^\n]*maxAudioBufferBytes/)
})

test('the drop counter mirrors the server reading and resets per turn', async () => {
  // The server sends `droppedFrames` as a cumulative count for the current
  // utterance. Two things have to hold for the panel's "已丢弃 N 帧" badge to mean
  // anything: the value must be mirrored rather than accumulated (adding a
  // running total on every frame turns 1, 2, 3 into 1, 3, 6), and a new turn must
  // start from zero instead of inheriting the previous turn's total.
  const { initialRealtimeState, realtimeReducer } = await loadStateModule()
  let state = realtimeReducer(initialRealtimeState, { type: 'buffer', bytes: 640, dropped: 0 })
  state = realtimeReducer(state, { type: 'buffer', bytes: 1280, dropped: 4 })
  state = realtimeReducer(state, { type: 'buffer', bytes: 1920, dropped: 7 })
  assert.equal(state.droppedFrames, 7)
  assert.equal(state.bufferedBytes, 1920)
  state = realtimeReducer(state, { type: 'revision', utteranceId: 'utt-2', revision: 2 })
  assert.equal(state.droppedFrames, 0)
})

test('audio queue events forward the server drop count to the reducer', async () => {
  // The server has always sent `droppedFrames` and the panel has always rendered
  // it; the event handler just never forwarded it, so a truncated question stayed
  // invisible in the UI even after the server stopped rejecting frames outright.
  const events = await readFile(fileURLToPath(new URL('../src/features/realtime/events.ts', import.meta.url)), 'utf8')
  assert.match(events, /type: 'buffer', bytes: event\.bufferedBytes \?\? 0, dropped: event\.droppedFrames \?\? 0/)
})
