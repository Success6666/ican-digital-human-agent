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

test('uses the documented streaming contract without relying on speak return values', async () => {
  const runtime = await readFile(fileURLToPath(new URL('../src/features/avatar/runtime/mofaRuntime.ts', import.meta.url)), 'utf8')
  assert.match(runtime, /private streamStarted = false/)
  assert.match(runtime, /speak\(text: string, isStart\?: boolean, isEnd\?: boolean, extra\?: Record<string, unknown>\): void/)
  assert.match(runtime, /private pendingSpeech\?/)
  assert.match(runtime, /this\.avatar\.speak\(request\.ssml, isStart, false, extra\)/)
  assert.match(runtime, /this\.avatar\.speak\(request\.ssml, isStart, true, extra\)/)
  assert.match(runtime, /private handleSpeakStateChange\(state: string, clientSpeakId\?: string \| number\)/)
  assert.match(runtime, /await completion\.promise/)
  assert.match(runtime, /this\.avatar\.interactiveidle\(\)/)
  assert.doesNotMatch(runtime, /client_speak_id:/)
  assert.doesNotMatch(runtime, /returnedSpeakId/)
  assert.doesNotMatch(runtime, /speechWaiters/)
  assert.match(runtime, /this\.streamStarted = false/)
  assert.match(runtime, /await withTimeout\(initPromise, 60_000\)/)
  assert.match(runtime, /await waitForStablePaint\(\)/)
  assert.doesNotMatch(runtime, /Promise\.race\(\[initPromise, firstFrame\]\)/)
  assert.match(runtime, /this\.assertConnectionActive\(connectionGeneration\)/)
})

test('enables the official SDK logger and emits runtime diagnostics', async () => {
  const runtime = await readFile(fileURLToPath(new URL('../src/features/avatar/runtime/mofaRuntime.ts', import.meta.url)), 'utf8')
  assert.match(runtime, /enableDebugger: false/)
  assert.match(runtime, /enableLogger: true/)
  assert.doesNotMatch(runtime, /enableDebugger: true/)
  assert.match(runtime, /function debugMofa\(event: string, detail\?: unknown\)/)
  assert.match(runtime, /debugMofa\('SDK init'/)
  assert.match(runtime, /debugMofa\('SDK message', message\)/)
  assert.match(runtime, /debugMofa\('SDK speak failed'/)
  assert.match(runtime, /function sanitizeMofaDiagnostic\(/)
  assert.match(runtime, /authorization\|secret\|token\|password\|cookie\|api\[-_\]\?key\|signature\|session/)
  assert.match(runtime, /sanitizeMofaUrl/)
  assert.match(runtime, /Bearer\\s\+/)
  assert.match(runtime, /acquireMofaConsoleGuard/)
  assert.match(runtime, /const safeDetail = sanitizeMofaString\(detail\)/)
  assert.doesNotMatch(runtime, /walk_version: 3/)
  assert.doesNotMatch(runtime, /framedata_proto_version: 2/)
  assert.doesNotMatch(runtime, /raw_audio: false/)
  assert.match(runtime, /avatar\.changeLayout\(/)
  assert.match(runtime, /onVoiceStateChange/)
  assert.match(runtime, /onNetworkInfo/)
  assert.match(runtime, /onStateRenderChange/)
})

test('does not submit masked Mofa credentials when only context settings change', async () => {
  const controls = await readFile(fileURLToPath(new URL('../src/features/runtime/components/ConfigurationControls.tsx', import.meta.url)), 'utf8')
  assert.match(controls, /function editableMofaValue\(value\?: string\)/)
  assert.match(controls, /const existingAppId = editableMofaValue\(configuration\?\.mofa\?\.appId\)/)
  assert.match(controls, /appId !== existingAppId/)
  assert.match(controls, /const existingAuthorization = editableMofaValue\(configuration\?\.mofa\?\.authorization\)/)
  assert.match(controls, /authorization !== existingAuthorization/)
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
  assert.match(runtime, /!initialized \|\| ttsaWarning \|\| rendered/)
  assert.doesNotMatch(runtime, /walk_version|framedata_proto_version|raw_audio/)
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

test('sends streaming segments with official start/end boundaries and waits only for the final callback', async () => {
  const Runtime = await loadRuntimeForTest()
  const runtime = new Runtime()
  const calls = []
  let interactiveIdleCalls = 0
  runtime.avatar = {
    speak(ssml, isStart, isEnd, extra) {
      calls.push({ ssml, isStart, isEnd, extra })
    },
    interrupt() { return 0 },
    interactiveidle() { interactiveIdleCalls += 1 },
  }

  const pending = runtime.speak('第一段。第二段。', undefined, { flush: true })
  await nextTask()
  assert.equal(calls.length, 2)
  assert.equal(calls[0].isStart, true)
  assert.equal(calls[0].isEnd, false)
  assert.equal(calls[1].isStart, false)
  assert.equal(calls[1].isEnd, true)

  runtime.handleSpeakStateChange('speak_start', 'sdk-speech-1')
  runtime.handleSpeakStateChange('speak_end', 'sdk-speech-1')
  await pending
  assert.equal(runtime.streamStarted, false)
  assert.equal(interactiveIdleCalls, 1)
})

test('keeps the final segment until the stream closes so it can be marked is_end', async () => {
  const Runtime = await loadRuntimeForTest()
  const runtime = new Runtime()
  const calls = []
  runtime.avatar = {
    speak(ssml, isStart, isEnd, extra) {
      calls.push({ ssml, isStart, isEnd, extra })
    },
    interrupt() { return 0 },
    interactiveidle() {},
  }

  await runtime.speak('第一段。')
  await nextTask()
  assert.equal(calls.length, 0)

  const pending = runtime.speak('', undefined, { flush: true })
  await nextTask()
  assert.equal(calls.length, 1)
  assert.equal(calls[0].isStart, true)
  assert.equal(calls[0].isEnd, true)
  runtime.handleSpeakStateChange('speak_start', 'sdk-speech-2')
  runtime.handleSpeakStateChange('speak_end', 'sdk-speech-2')
  await pending
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
