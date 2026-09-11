import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'
import * as ts from 'typescript'

const sourcePath = fileURLToPath(new URL('../src/features/avatar/runtime/audioUnlock.ts', import.meta.url))

/**
 * Load `audioUnlock` against a fake WebAudio implementation.
 *
 * Mobile behaviour is modelled by starting every context `suspended`, and by
 * only letting `resume()` succeed while `inGesture()` is true — that is the
 * rule which leaves a phone silent when nothing ever unlocked the page.
 */
async function loadAudioUnlock(options = {}) {
  const inGesture = options.inGesture ?? (() => true)
  // When set, `resume()` parks on this promise, modelling a gesture that has
  // already expired by the time the browser gets round to resuming.
  const resumeGate = options.resumeGate
  const contexts = []

  class FakeAudioContext {
    constructor() {
      this.state = 'suspended'
      this.sampleRate = 48_000
      this.destination = {}
      this.startedSources = []
      contexts.push(this)
    }
    async resume() {
      if (!inGesture()) throw new Error('resume requires a user gesture')
      if (resumeGate) await resumeGate
      this.state = 'running'
    }
    createBuffer() {
      return { duration: 0 }
    }
    createBufferSource() {
      const owner = this
      return {
        buffer: undefined,
        connect() {},
        start() {
          owner.startedSources.push(1)
        },
      }
    }
  }

  const source = await readFile(sourcePath, 'utf8')
  const output = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
  }).outputText

  const windowStub = { AudioContext: FakeAudioContext }
  const documentListeners = []
  const module = { exports: {} }
  vm.runInNewContext(output, {
    module,
    exports: module.exports,
    window: windowStub,
    document: {
      addEventListener(event, handler) { documentListeners.push({ event, handler }) },
      removeEventListener(event, handler) {
        const index = documentListeners.findIndex((entry) => entry.event === event && entry.handler === handler)
        if (index >= 0) documentListeners.splice(index, 1)
      },
    },
  })

  return {
    api: module.exports,
    contexts,
    documentListeners,
    windowStub,
  }
}

test('reports suspended until a gesture unlocks audio', async () => {
  const { api } = await loadAudioUnlock()
  const before = api.avatarAudioState()
  assert.equal(before.state, 'suspended')
  assert.equal(before.unlocked, false)

  const after = await api.unlockAvatarAudio()
  assert.equal(after.state, 'running')
  assert.equal(after.unlocked, true)
})

test('plays a silent buffer so iOS treats the page as unlocked', async () => {
  const { api, contexts } = await loadAudioUnlock()
  await api.unlockAvatarAudio()
  assert.equal(contexts.length, 1)
  // `resume()` alone is not enough on iOS; a started source is what counts.
  assert.equal(contexts[0].startedSources.length, 1)
})

test('starts the silent buffer before awaiting resume so iOS still sees a gesture', async () => {
  let release
  const gate = new Promise((resolve) => { release = resolve })
  const { api, contexts } = await loadAudioUnlock({ resumeGate: gate })
  const unlocking = api.unlockAvatarAudio()
  await new Promise((resolve) => setImmediate(resolve))
  // Parked on `resume()`: the gesture may already be over, so the silent
  // source has to have been started while it was still live.
  assert.equal(contexts[0].startedSources.length, 1)
  release()
  await unlocking
  assert.equal(api.avatarAudioState().unlocked, true)
})

test('forgets contexts the page has closed instead of tracking them forever', async () => {
  const { api, contexts } = await loadAudioUnlock()
  await api.unlockAvatarAudio()
  assert.equal(api.avatarAudioState().trackedCount, 1)
  // A long session repeatedly builds and tears down contexts.
  contexts[0].state = 'closed'
  api.resumeTrackedAudio()
  assert.equal(api.avatarAudioState().trackedCount, 0)
})

test('a blocked unlock stays suspended instead of throwing', async () => {
  // No gesture — the normal case when the avatar speaks from an inbound
  // websocket delta rather than from a tap.
  const { api } = await loadAudioUnlock({ inGesture: () => false })
  const state = await api.unlockAvatarAudio()
  assert.equal(state.state, 'suspended')
  assert.equal(state.unlocked, false)
})

test('reports unsupported when WebAudio is missing', async () => {
  const source = await readFile(sourcePath, 'utf8')
  const output = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(output, { module, exports: module.exports, window: {}, document: undefined })
  const state = module.exports.avatarAudioState()
  assert.equal(state.state, 'unsupported')
  assert.equal(state.unlocked, false)
})

test('tracks the context the vendor SDK creates and resumes it too', async () => {
  const { api, contexts, windowStub } = await loadAudioUnlock()
  api.installAudioContextTracker()
  // The SDK builds its own context after the tracker is installed, and we
  // never receive a reference to it.
  const sdkContext = new windowStub.AudioContext()
  assert.equal(sdkContext.state, 'suspended')
  assert.equal(api.avatarAudioState().trackedCount, 1)

  await api.unlockAvatarAudio()
  // Our own context and the SDK's must both end up running.
  assert.equal(contexts.length, 2)
  for (const context of contexts) assert.equal(context.state, 'running')
})

test('re-resumes tracked contexts that lapsed back to suspended', async () => {
  const { api, contexts } = await loadAudioUnlock()
  await api.unlockAvatarAudio()
  assert.equal(contexts[0].state, 'running')
  // A background tab or an incoming call can suspend a context again.
  contexts[0].state = 'suspended'
  api.resumeTrackedAudio()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(contexts[0].state, 'running')
})

test('binds a capture-phase gesture listener and removes it on cleanup', async () => {
  const { api, documentListeners } = await loadAudioUnlock()
  assert.equal(documentListeners.length, 0)
  const release = api.bindGestureAudioUnlock()
  // Touches matter as much as clicks: a phone has no mouse.
  assert.ok(documentListeners.some((entry) => entry.event === 'touchend'))
  assert.ok(documentListeners.some((entry) => entry.event === 'pointerdown'))
  release()
  assert.equal(documentListeners.length, 0)
})
