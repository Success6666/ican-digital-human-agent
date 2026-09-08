import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'
import * as ts from 'typescript'

const sourcePath = fileURLToPath(new URL('../src/features/avatar/runtime/mofaSpeech.ts', import.meta.url))
const source = await readFile(sourcePath, 'utf8')
const output = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
}).outputText
const moduleUrl = `data:text/javascript;base64,${Buffer.from(output).toString('base64')}`
const { buildMofaSpeechRequest, MOFA_ACTION_INTENTS, MOFA_EMOTIONS } = await import(moduleUrl)

test('builds valid SSML and emits all documented emotions only when enabled', () => {
  const request = buildMofaSpeechRequest(' 你好 <世界> ', { expression: 'happy' }, { enableEmotion: true })
  assert.equal(request.ssml, '<speak>你好 &lt;世界&gt;</speak>')
  assert.deepEqual(request.extra, { emotion: 'happy' })
  assert.deepEqual(MOFA_EMOTIONS, ['happy', 'sad', 'angry', 'surprised', 'neutral'])
  for (const emotion of MOFA_EMOTIONS) {
    assert.deepEqual(
      buildMofaSpeechRequest('情感测试', { expression: emotion }, { enableEmotion: true }).extra,
      { emotion },
    )
  }
  assert.deepEqual(buildMofaSpeechRequest('普通角色', { expression: 'happy' }).extra, {})
  assert.deepEqual(buildMofaSpeechRequest('未知情感', { expression: 'serious' }, { enableEmotion: true }).extra, {})
})

test('emits the complete documented action-intent catalog with exact names', () => {
  assert.equal(MOFA_ACTION_INTENTS.length, 70)
  for (const action of MOFA_ACTION_INTENTS) {
    const request = buildMofaSpeechRequest('动作测试', { expression: 'neutral', action })
    assert.equal(
      request.ssml,
      `<speak><ue4event><type>ka_intent</type><data><ka_intent>${action}</ka_intent></data></ue4event>动作测试</speak>`,
    )
  }
  assert.match(buildMofaSpeechRequest('重点', { action: 'KeyPoints' }).ssml, /<type>ka_intent<\/type>/)
  assert.match(buildMofaSpeechRequest('提高', { action: 'Elevate' }).ssml, /<ka_intent>Elevate<\/ka_intent>/)
})

test('rejects undocumented aliases and role-specific concrete key actions', () => {
  for (const action of ['greet', 'wave_hand', 'nod', 'small_nod', 'RightSide02']) {
    assert.equal(buildMofaSpeechRequest('继续播报', { expression: 'neutral', action }).ssml, '<speak>继续播报</speak>')
  }
})

test('streams avatar sentence chunks without reopening every sentence', async () => {
  const runtime = await readFile(fileURLToPath(new URL('../src/features/avatar/runtime/mofaRuntime.ts', import.meta.url)), 'utf8')
  assert.match(runtime, /private streamStarted = false/)
  assert.match(runtime, /this\.avatar\.speak\(request\.ssml, isStart, isEnd, extra\)/)
  assert.match(runtime, /const clientSpeakId = String\(returnedSpeakId\)/)
  assert.match(runtime, /const key = String\(clientSpeakId\)/)
  assert.doesNotMatch(runtime, /client_speak_id:/)
  assert.match(runtime, /const isEnd = this\.speechFlushRequested && this\.speechQueue\.length === 0/)
  assert.doesNotMatch(runtime, /Keep the last non-final sentence pending/)
  assert.match(runtime, /Every chunk must wait for its own speak_end/)
  assert.match(runtime, /this\.speechWaiters\.set\(clientSpeakId/)
  assert.match(runtime, /await completion/)
  assert.match(runtime, /if \(this\.speechFlushRequested && !this\.speechQueue\.length && !this\.speechBuffer\.trim\(\)\)/)
  assert.match(runtime, /this\.streamStarted = false/)
  assert.match(runtime, /await withTimeout\(initPromise, 60_000\)/)
  assert.match(runtime, /await waitForStablePaint\(\)/)
  assert.doesNotMatch(runtime, /Promise\.race\(\[initPromise, firstFrame\]\)/)
  assert.match(runtime, /this\.speechQueue\.length && this\.canDrainSpeechQueue\(\)/)
  assert.match(runtime, /return this\.speechFlushRequested \|\| this\.speechQueue\.length > 1 \|\| Boolean\(this\.speechBuffer\.trim\(\)\)/)
})

test('normalizes TTSA session gateway URLs to HTTP schemes and keeps reconnect cursor', async () => {
  const runtime = await readFile(fileURLToPath(new URL('../src/features/avatar/runtime/mofaRuntime.ts', import.meta.url)), 'utf8')
  assert.match(runtime, /function normalizeGatewayUrl\(value: string\): URL/)
  assert.match(runtime, /gateway\.protocol === 'wss:'/)
  assert.match(runtime, /gateway\.protocol = 'https:'/)
  assert.match(runtime, /魔珐会话网关必须使用 http 或 https/)
  assert.doesNotMatch(runtime, /gateway\.protocol = 'wss:'/)
  assert.match(runtime, /isRecoverableTtsaError/)
  assert.match(runtime, /暂无空闲房间/)
  assert.match(runtime, /phase: 'warning'/)
  assert.match(runtime, /if \(ttsaWarning\) return/)
  const surface = await readFile(fileURLToPath(new URL('../src/features/avatar/runtime/AvatarRuntimeSurface.tsx', import.meta.url)), 'utf8')
  assert.match(surface, /const currentSpeechMessageId = speech\?\.id\?\.split\(':', 1\)\[0\]/)
  assert.match(surface, /spokenTextRef\.current = speech\?\.text \?\? ''/)
})

test('generates runtime ids when randomUUID is unavailable on public HTTP', async () => {
  const runtimeIdPath = fileURLToPath(new URL('../src/features/avatar/runtime/runtimeId.ts', import.meta.url))
  const runtimeIdSource = await readFile(runtimeIdPath, 'utf8')
  const runtimeIdOutput = ts.transpileModule(runtimeIdSource, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
  }).outputText
  const runtimeIdModule = await import(`data:text/javascript;base64,${Buffer.from(runtimeIdOutput).toString('base64')}`)
  let next = 0
  const source = {
    getRandomValues(buffer) {
      for (let index = 0; index < buffer.length; index += 1) buffer[index] = next++
      return buffer
    },
  }
  const id = runtimeIdModule.createRuntimeId(source)
  assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}$/)
})

test('waits for each speak_end before dispatching the next fast stream segment', async () => {
  const Runtime = await loadRuntimeForTest()
  const runtime = new Runtime()
  const calls = []
  runtime.avatar = {
    speak(ssml, isStart, isEnd, extra) {
      const id = `sdk-speech-${calls.length + 1}`
      calls.push({ ssml, isStart, isEnd, extra, id })
      return id
    },
    interrupt() { return 0 },
  }

  const pending = runtime.speak('第一段。第二段。', undefined, { flush: true })
  await nextTask()
  assert.equal(calls.length, 1)
  assert.equal(calls[0].isStart, true)
  assert.equal(calls[0].isEnd, false)

  runtime.speechWaiters.get(calls[0].id).resolve()
  await nextTask()
  assert.equal(calls.length, 2)
  assert.equal(calls[1].isStart, false)
  assert.equal(calls[1].isEnd, true)

  runtime.speechWaiters.get(calls[1].id).resolve()
  await pending
  assert.equal(runtime.streamStarted, false)
})

test('dispatches the first complete sentence immediately and closes an empty flush', async () => {
  const Runtime = await loadRuntimeForTest()
  const runtime = new Runtime()
  const calls = []
  runtime.avatar = {
    speak(ssml, isStart, isEnd, extra) {
      const id = calls.length + 1
      calls.push({ ssml, isStart, isEnd, extra, id: String(id) })
      return id
    },
    interrupt() { return 0 },
  }

  const pending = runtime.speak('第一段。')
  await nextTask()
  assert.equal(calls.length, 1)
  runtime.speechWaiters.get(calls[0].id).resolve()
  await pending
  assert.equal(runtime.streamStarted, true)

  await runtime.speak('', undefined, { flush: true })
  assert.equal(runtime.streamStarted, false)
})

async function loadRuntimeForTest() {
  const runtimeSource = await readFile(fileURLToPath(new URL('../src/features/avatar/runtime/mofaRuntime.ts', import.meta.url)), 'utf8')
  const runtimeOutput = ts.transpileModule(runtimeSource, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
  }).outputText
  const module = { exports: {} }
  const context = {
    module,
    exports: module.exports,
    require(specifier) {
      if (specifier.endsWith('/mofaSpeech')) return { buildMofaSpeechRequest: (text) => ({ ssml: text, extra: {} }) }
      if (specifier.endsWith('/runtimeId')) return { createRuntimeId: (() => { let id = 0; return () => `speech-${++id}` })() }
      if (specifier.endsWith('/scriptLoader')) return { loadExternalScript: async () => undefined }
      return {}
    },
    window: { setTimeout, clearTimeout, requestAnimationFrame: (callback) => setTimeout(callback, 0) },
    console,
    URL,
  }
  vm.runInNewContext(runtimeOutput, context)
  return module.exports.MofaBrowserRuntime
}

function nextTask() {
  return new Promise((resolve) => setImmediate(resolve))
}
