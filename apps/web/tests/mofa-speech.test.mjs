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
  assert.match(runtime, /!initialized/)
  assert.match(runtime, /ttsaWarning/)
  assert.match(runtime, /rendered = true/)
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
  const { Runtime } = await loadRuntimeForTest()
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
  // Only the first clause is handed over: the second waits for the SDK to
  // acknowledge it, instead of both racing and one being dropped.
  assert.equal(calls.length, 1)
  assert.equal(calls[0].isStart, true)
  assert.equal(calls[0].isEnd, false)
  // The stream is parked on the SDK acknowledging this clause, and only then
  // hands over the next one.
  assert.ok(runtime.segmentAck)

  runtime.handleSpeakStateChange('speak_start', 'sdk-speech-1')
  await nextTask()
  assert.equal(calls.length, 2)
  assert.equal(calls[1].isStart, false)
  assert.equal(calls[1].isEnd, true)
  // The final segment never waits on an acknowledgement: it is already
  // awaited through the completion promise.
  assert.equal(runtime.segmentAck, undefined)

  runtime.handleSpeakStateChange('speak_end', 'sdk-speech-1')
  await pending
  assert.equal(runtime.streamStarted, false)
  assert.equal(interactiveIdleCalls, 1)
})

test('releases the next segment after an ack timeout when the SDK stays silent', async () => {
  const { Runtime, reported } = await loadRuntimeForTest()
  const runtime = new Runtime()
  const calls = []
  runtime.avatar = {
    speak(ssml, isStart, isEnd) { calls.push({ ssml, isStart, isEnd }) },
    interrupt() { return 0 },
    interactiveidle() {},
  }
  runtime.setTraceContext({ traceId: () => 'trace-ack', runId: () => undefined, utteranceId: () => undefined, revision: () => undefined })

  const pending = runtime.speak('第一段。第二段。', undefined, { flush: true })
  await nextTask()
  assert.equal(calls.length, 1)
  // No `speak_start` ever arrives; the timeout must still let the tail out.
  await new Promise((resolve) => setTimeout(resolve, 1_300))
  assert.equal(calls.length, 2)
  assert.equal(calls[1].isEnd, true)
  const timeout = reported.find((event) => event.name === 'speech.ack_timeout')
  assert.ok(timeout)
  assert.equal(timeout.status, 'error')
  runtime.handleSpeakStateChange('speak_end', 'sdk-ack')
  await pending
})

test('merges text still buffered at flush time instead of dropping it', async () => {
  const { Runtime } = await loadRuntimeForTest()
  const runtime = new Runtime()
  const calls = []
  runtime.avatar = {
    speak(ssml, isStart, isEnd) { calls.push({ ssml, isStart, isEnd }) },
    interrupt() { return 0 },
    interactiveidle() {},
  }

  // "好的" is under the opening threshold, so it stays buffered.
  await runtime.speak('好的')
  await nextTask()
  assert.equal(calls.length, 0)
  assert.equal(runtime.speechBuffer, '好的')

  const pending = runtime.speak('没问题。', undefined, { flush: true })
  await nextTask()
  assert.equal(calls.length, 1)
  assert.equal(calls[0].isStart, true)
  assert.equal(calls[0].isEnd, true)
  // The short fragment must ride along with the final clause.
  assert.match(calls[0].ssml, /好的/)
  assert.match(calls[0].ssml, /没问题/)
  assert.equal(runtime.speechBuffer, '')
  runtime.handleSpeakStateChange('speak_start', 'sdk-merge')
  runtime.handleSpeakStateChange('speak_end', 'sdk-merge')
  await pending
})

test('serializes concurrent speak calls so no segment is overwritten', async () => {
  const { Runtime } = await loadRuntimeForTest()
  const runtime = new Runtime()
  const calls = []
  runtime.avatar = {
    speak(ssml, isStart, isEnd) { calls.push({ ssml, isStart, isEnd }) },
    interrupt() { return 0 },
    interactiveidle() {},
  }

  // React re-runs the speech effect on every delta without awaiting. These
  // four overlapping calls must still arrive in order.
  const first = runtime.speak('第一句。')
  const second = runtime.speak('第二句。')
  const third = runtime.speak('第三句。')
  const fourth = runtime.speak('', undefined, { flush: true })
  await nextTask()
  assert.equal(calls.length, 1)
  assert.match(calls[0].ssml, /第一句/)

  runtime.handleSpeakStateChange('speak_start', 's1')
  await nextTask()
  assert.equal(calls.length, 2)
  assert.match(calls[1].ssml, /第二句/)

  runtime.handleSpeakStateChange('speak_start', 's2')
  await nextTask()
  assert.equal(calls.length, 3)
  assert.match(calls[2].ssml, /第三句/)

  runtime.handleSpeakStateChange('speak_start', 's3')
  await nextTask()
  assert.equal(calls.length, 3)
  runtime.handleSpeakStateChange('speak_end', 's3')
  await nextTask()
  await Promise.all([first, second, third, fourth])
  assert.equal(runtime.streamStarted, false)
})

test('reports a dropped segment instead of losing it silently', async () => {
  const { Runtime, reported } = await loadRuntimeForTest()
  const runtime = new Runtime()
  runtime.setTraceContext({ traceId: () => 'trace-drop', runId: () => undefined, utteranceId: () => undefined, revision: () => undefined })
  // No avatar instance: the segment cannot be handed over and must be visible.
  await runtime.dispatchSpeechSegment({ text: '被丢弃的内容' }, true, runtime.speechGeneration)
  const dropped = reported.find((event) => event.name === 'speech.dropped')
  assert.ok(dropped)
  assert.equal(dropped.status, 'error')
  assert.equal(dropped.attributes.reason, 'avatar_unavailable')
  assert.equal(dropped.attributes.textLength, 6)
})

test('drops a segment whose utterance was abandoned while it waited its turn', async () => {
  const { Runtime, reported } = await loadRuntimeForTest()
  const runtime = new Runtime()
  const calls = []
  runtime.avatar = {
    speak(ssml, isStart, isEnd) { calls.push({ ssml, isStart, isEnd }) },
    interrupt() { return 0 },
    interactiveidle() {},
  }
  runtime.setTraceContext({ traceId: () => 'trace-stale', runId: () => undefined, utteranceId: () => undefined, revision: () => undefined })

  // A generation from an utterance that is already gone.
  await runtime.dispatchSpeechSegment({ text: '上一轮残留' }, true, runtime.speechGeneration + 1)
  assert.equal(calls.length, 0)
  const dropped = reported.find((event) => event.name === 'speech.dropped')
  assert.ok(dropped)
  assert.equal(dropped.attributes.reason, 'generation_changed')
  assert.equal(dropped.attributes.textLength, 5)
})

test('an interrupt mid-stream keeps the abandoned answer out of the next one', async () => {
  const { Runtime } = await loadRuntimeForTest()
  const runtime = new Runtime()
  const calls = []
  runtime.avatar = {
    speak(ssml, isStart, isEnd) { calls.push({ ssml, isStart, isEnd }) },
    interrupt() { return 0 },
    interactiveidle() {},
  }

  // Two clauses in one pass: the first goes out, the second waits for the SDK
  // to acknowledge it. That wait is exactly where a barge-in lands.
  const abandoned = runtime.speak('第一段。第二段。', undefined, { flush: true })
  await nextTask()
  assert.equal(calls.length, 1)

  await runtime.interrupt()
  // The clause was cut before the wait, so without a guard it would be
  // re-queued here and open the *next* answer.
  assert.equal(runtime.pendingSpeech, undefined)
  assert.equal(runtime.speechBuffer, '')
  await abandoned

  const next = runtime.speak('新的回答。', undefined, { flush: true })
  await nextTask()
  assert.equal(calls.length, 2)
  assert.match(calls[1].ssml, /新的回答/)
  assert.doesNotMatch(calls[1].ssml, /第二段/)
  runtime.handleSpeakStateChange('speak_start', 'sdk-next')
  runtime.handleSpeakStateChange('speak_end', 'sdk-next')
  await next
})

test('records how much speech was discarded when an interrupt arrives', async () => {
  const { Runtime, reported } = await loadRuntimeForTest()
  const runtime = new Runtime()
  runtime.avatar = {
    speak() {},
    interrupt() { return 0 },
    interactiveidle() {},
  }
  runtime.setTraceContext({ traceId: () => 'trace-interrupt', runId: () => undefined, utteranceId: () => undefined, revision: () => undefined })
  // Buffer a clause below the release threshold, then interrupt mid-answer.
  await runtime.speak('还没说出口的话')
  await runtime.interrupt()
  const interrupted = reported.find((event) => event.name === 'speech.interrupted')
  assert.ok(interrupted)
  assert.equal(interrupted.attributes.pendingLength, 7)
  assert.equal(runtime.speechBuffer, '')
})

test('keeps the final segment until the stream closes so it can be marked is_end', async () => {
  const { Runtime } = await loadRuntimeForTest()
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

test('reports the speak lifecycle onto the shared trace once a trace exists', async () => {
  const { Runtime, reported } = await loadRuntimeForTest()
  const runtime = new Runtime()
  runtime.avatar = {
    speak() {},
    interrupt() { return 0 },
    interactiveidle() {},
  }
  // No trace yet: the avatar runtime must stay silent rather than invent one.
  runtime.setTraceContext({
    traceId: () => undefined,
    runId: () => undefined,
    utteranceId: () => undefined,
    revision: () => undefined,
  })
  runtime.handleSpeakStateChange('speak_start', 'sdk-1')
  assert.equal(reported.length, 0)

  runtime.setTraceContext({
    traceId: () => 'trace-1',
    runId: () => 'run-1',
    utteranceId: () => 'utt-1',
    revision: () => 4,
  })
  runtime.handleSpeakStateChange('speak_start', 'sdk-1')
  assert.equal(reported.length, 1)
  assert.equal(reported[0].name, 'speak.started')
  assert.equal(reported[0].traceId, 'trace-1')
  assert.equal(reported[0].runId, 'run-1')
  assert.equal(reported[0].utteranceId, 'utt-1')
  assert.equal(reported[0].revision, 4)

  // An error transition marks the trace and carries no SSML or audio.
  runtime.handleSpeakStateChange('speak_error', 'sdk-1')
  const failure = reported.find((event) => event.name === 'speak.failed')
  assert.ok(failure)
  assert.equal(failure.status, 'error')
  assert.equal(JSON.stringify(reported).includes('ssml'), false)
})

test('marks a TTSA warning once and clears it when the session recovers', async () => {
  const { Runtime, reported } = await loadRuntimeForTest()
  const runtime = new Runtime()
  runtime.setTraceContext({
    traceId: () => 'trace-ttsa',
    runId: () => undefined,
    utteranceId: () => undefined,
    revision: () => undefined,
  })
  runtime.markTtsaWarning({ code: 40006 }, '暂无空闲房间')
  // Repeated warnings must not flood the trace.
  runtime.markTtsaWarning({ code: 40006 }, '暂无空闲房间')
  const warnings = reported.filter((event) => event.name === 'ttsa.warning')
  assert.equal(warnings.length, 1)
  assert.equal(warnings[0].status, 'error')

  runtime.markTtsaRecovered()
  runtime.markTtsaRecovered()
  assert.equal(reported.filter((event) => event.name === 'ttsa.recovered').length, 1)
})

test('uses a monotonic fallback clock when performance is unavailable', async () => {
  const { Runtime } = await loadRuntimeForTest({ reportClientEvent: () => undefined })
  const runtime = new Runtime()
  // The guarded clock must not throw in a sandbox without `performance`.
  assert.doesNotThrow(() => runtime.setTraceContext({
    traceId: () => 'trace-clock',
    runId: () => undefined,
    utteranceId: () => undefined,
    revision: () => undefined,
  }))
  assert.doesNotThrow(() => runtime.handleSpeakStateChange('speak_start', 'sdk-clock'))
})

test('reports blocked audio when the page was never unlocked', async () => {
  // A phone that never received a gesture: the context is suspended and every
  // utterance would be rendered in silence.
  const { Runtime, reported } = await loadRuntimeForTest({
    audioUnlock: audioStateStub('suspended'),
  })
  const runtime = new Runtime()
  runtime.setTraceContext({ traceId: () => 'trace-audio', runId: () => undefined, utteranceId: () => undefined, revision: () => undefined })
  runtime.avatar = { speak() {}, interrupt: () => 0, interactiveidle() {} }

  const pending = runtime.dispatchSpeechSegment({ text: '测试内容' }, false, runtime.speechGeneration)
  runtime.handleSpeakStateChange('speak_start', 'a1')
  await pending

  const blocked = reported.find((event) => event.name === 'avatar.audio_blocked')
  assert.ok(blocked)
  assert.equal(blocked.status, 'error')
  assert.equal(blocked.attributes.state, 'suspended')
})

test('reports the audio state once per change, not once per segment', async () => {
  let state = 'suspended'
  const audio = {
    installAudioContextTracker() {},
    resumeTrackedAudio() {},
    avatarAudioState: () => ({ state, unlocked: state === 'running', trackedCount: 1 }),
  }
  const { Runtime, reported } = await loadRuntimeForTest({ audioUnlock: audio })
  const runtime = new Runtime()
  runtime.setTraceContext({ traceId: () => 'trace-audio2', runId: () => undefined, utteranceId: () => undefined, revision: () => undefined })
  runtime.avatar = { speak() {}, interrupt: () => 0, interactiveidle() {} }

  const speakOnce = async (text, id) => {
    const pending = runtime.dispatchSpeechSegment({ text }, false, runtime.speechGeneration)
    runtime.handleSpeakStateChange('speak_start', id)
    await pending
  }

  await speakOnce('第一句', 'a1')
  assert.equal(reported.filter((event) => event.name === 'avatar.audio_blocked').length, 1)
  // Still suspended: repeating the marker would bury the rest of the trace.
  await speakOnce('第二句', 'a2')
  assert.equal(reported.filter((event) => event.name === 'avatar.audio_blocked').length, 1)

  // The user taps, and the page finally unlocks.
  state = 'running'
  await speakOnce('第三句', 'a3')
  const unlocked = reported.filter((event) => event.name === 'avatar.audio_unlocked')
  assert.equal(unlocked.length, 1)
  assert.equal(unlocked[0].attributes.state, 'running')
})

test('a new user turn only pre-empts speech that is actually playing', async () => {
  const surface = await readFile(fileURLToPath(new URL('../src/features/avatar/runtime/AvatarRuntimeSurface.tsx', import.meta.url)), 'utf8')
  // The stage must not stop the avatar just because a key showed up: reading
  // "the avatar started speaking" as a new turn is exactly how the opening
  // sentence of a reply used to be discarded. A turn is also honoured once, so
  // an unrelated re-render cannot stop the avatar again.
  assert.match(surface, /handledInterruptKeyRef/)
  assert.match(surface, /if \(statusPhaseRef\.current !== 'speaking'\) return/)
  // One failed utterance must not disable the runtime for the rest of the
  // session: `error` makes the delta guard skip every later delta.
  assert.doesNotMatch(surface, /setStatus\(\{ phase: 'error', message: '数字人播报失败，请重新连接' \}\)/)
})

test('bounds the first-paint wait so an unpainted tab still reaches ready', async () => {
  const runtime = await readFile(fileURLToPath(new URL('../src/features/avatar/runtime/mofaRuntime.ts', import.meta.url)), 'utf8')
  // A background or occluded window can stop delivering animation frames. An
  // unbounded rAF wait left the runtime stuck on "正在加载数字人资源 80%"
  // forever instead of reporting ready, which also blocks all conversation.
  assert.match(runtime, /async function waitForStablePaint\(timeoutMs = 1_000\): Promise<void>/)
  assert.match(runtime, /Promise\.race\(\[\s*new Promise<void>\(\(resolve\) => window\.requestAnimationFrame/)
})

test('stays usable after a segment fails so the next answer is not lost', async () => {
  const { Runtime } = await loadRuntimeForTest()
  const runtime = new Runtime()
  const calls = []
  runtime.avatar = {
    speak(ssml, isStart, isEnd) { calls.push({ ssml, isStart, isEnd }) },
    interrupt() { return 0 },
    interactiveidle() {},
  }

  // A rejected final segment abandons the utterance. The timeout path resets
  // the same flags, so this exercises the shared recovery.
  const failed = runtime.speak('失败的一段。', undefined, { flush: true })
  await nextTask()
  assert.equal(calls.length, 1)
  assert.equal(calls[0].isEnd, true)
  runtime.handleSpeakStateChange('speak_error', 'sdk-fail')
  await assert.rejects(failed)
  // Left mid-stream, the next reply would be submitted as a *continuation* of
  // the answer that died instead of opening its own utterance.
  assert.equal(runtime.streamStarted, false)

  const next = runtime.speak('新的回答。', undefined, { flush: true })
  await nextTask()
  assert.equal(calls.length, 2)
  assert.equal(calls[1].isStart, true)
  assert.match(calls[1].ssml, /新的回答/)
  runtime.handleSpeakStateChange('speak_start', 'sdk-next')
  runtime.handleSpeakStateChange('speak_end', 'sdk-next')
  await next
})

/**
 * Stand-in for the audio unlock module.
 *
 * `resumeTrackedAudio` deliberately does nothing while suspended: that mirrors
 * a phone where no gesture ever unlocked the page, and is the case the runtime
 * has to report rather than silently accept.
 */
function audioStateStub(state) {
  return {
    installAudioContextTracker() {},
    resumeTrackedAudio() {},
    avatarAudioState: () => ({ state, unlocked: state === 'running', trackedCount: 1 }),
  }
}

function createAudioUnlockStub(initialState) {
  const state = { value: initialState }
  return {
    setState(next) { state.value = next },
    installAudioContextTracker() {},
    resumeTrackedAudio() {},
    avatarAudioState: () => ({
      state: state.value,
      unlocked: state.value === 'running',
      trackedCount: 1,
    }),
  }
}

async function loadRuntimeForTest(options = {}) {
  const runtimeSource = await readFile(fileURLToPath(new URL('../src/features/avatar/runtime/mofaRuntime.ts', import.meta.url)), 'utf8')
  const runtimeOutput = ts.transpileModule(runtimeSource, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
  }).outputText
  const module = { exports: {} }
  // Capture telemetry so tests can assert what the vendor SDK lifecycle
  // reported onto the shared trace, without pulling in the real transport.
  const reported = []
  const reportClientEvent = options.reportClientEvent ?? ((event) => { reported.push(event) })
  const context = {
    module,
    exports: module.exports,
    require(specifier) {
      if (specifier.endsWith('/mofaSpeech')) return { buildMofaSpeechRequest: (text) => ({ ssml: text, extra: {} }) }
      if (specifier.endsWith('/runtimeId')) return { createRuntimeId: (() => { let id = 0; return () => `speech-${++id}` })() }
      if (specifier.endsWith('/scriptLoader')) return { loadExternalScript: async () => undefined }
      if (specifier.includes('clientReporter')) return { reportClientEvent }
      if (specifier.endsWith('/audioUnlock')) return options.audioUnlock ?? createAudioUnlockStub(options.audioState ?? 'suspended')
      return {}
    },
    window: { setTimeout, clearTimeout, requestAnimationFrame: (callback) => setTimeout(callback, 0) },
    performance: typeof performance === 'undefined' ? undefined : performance,
    Date,
    console,
    URL,
  }
  vm.runInNewContext(runtimeOutput, context)
  return { Runtime: module.exports.MofaBrowserRuntime, reported }
}

function nextTask() {
  return new Promise((resolve) => setImmediate(resolve))
}
