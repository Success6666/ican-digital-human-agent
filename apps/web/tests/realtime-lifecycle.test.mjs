import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import * as ts from 'typescript'

const gateSource = await readFile(fileURLToPath(new URL('../src/features/realtime/eventGate.ts', import.meta.url)), 'utf8')
const gateOutput = ts.transpileModule(gateSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
}).outputText
const gateModule = await import(`data:text/javascript;base64,${Buffer.from(gateOutput).toString('base64')}`)

test('late events from a completed run are ignored after run_done', () => {
  const gate = new gateModule.RealtimeEventGate()
  gate.reset('utt-1', 1)
  assert.ok(gate.accept({ type: 'run_started', runId: 'run-1', revision: 1 }))
  gate.markRunTerminal('run-1')
  assert.equal(gate.accept({ type: 'delta', runId: 'run-1', revision: 1, text: 'late' }), null)
  assert.ok(gate.accept({ type: 'run_started', runId: 'run-2', revision: 2 }))
})

test('browser voice is configured as a continuous recognition session', async () => {
  const source = await readFile(fileURLToPath(new URL('../src/features/realtime/browserSpeech.ts', import.meta.url)), 'utf8')
  assert.match(source, /recognition\.continuous\s*=\s*true/)
})

test('continuous voice requires a ready avatar and does not create sessions from typing', async () => {
  const source = await readFile(fileURLToPath(new URL('../src/features/chat/components/HomeConversationBar.tsx', import.meta.url)), 'utf8')
  assert.match(source, /sessionRef\.current\s*=\s*session/)
  assert.match(source, /const interactionReady = Boolean\(session && avatarReady\)/)
  assert.match(source, /if \(!message \|\| !interactionReady \|\| isCreating\) return/)
  assert.match(source, /disabled=\{!interactionReady \|\| isCreating\}/)
  assert.doesNotMatch(source, /onCreateSessionRef/)
  assert.match(source, /onSendRef\.current\(finalText\)/)
  assert.match(source, /const sent = realtime\.sendText\(finalText\)/)
  assert.match(source, /if \(!sent\) onSendRef\.current\(finalText\)/)
})

test('microphone feedback exposes normalized level and silence auto-stop', async () => {
  const pcm = await readFile(fileURLToPath(new URL('../src/features/realtime/pcm16.ts', import.meta.url)), 'utf8')
  const runtime = await readFile(fileURLToPath(new URL('../src/features/realtime/runtime.ts', import.meta.url)), 'utf8')
  const button = await readFile(fileURLToPath(new URL('../src/features/chat/components/HomeConversationBar.tsx', import.meta.url)), 'utf8')
  assert.match(pcm, /onLevel\?\.\(Math\.min\(1, Math\.sqrt\(energy \/ resampled\.length\) \* 4\)\)/)
  assert.match(runtime, /this\.silenceTimer = setTimeout\(/)
  assert.match(runtime, /this\.silenceTimer = undefined/)
  assert.match(runtime, /void this\.stopRecording\(\)/)
  assert.match(button, /--voice-level/)
})

test('voice mode automatically resumes listening after a completed turn', async () => {
  const source = await readFile(fileURLToPath(new URL('../src/features/chat/components/HomeConversationBar.tsx', import.meta.url)), 'utf8')
  const home = await readFile(fileURLToPath(new URL('../src/pages/HomePage.tsx', import.meta.url)), 'utf8')
  assert.match(source, /continuousVoiceActive/)
  assert.match(source, /realtime\.state\.phase !== 'idle'/)
  assert.match(source, /realtime\.startRecording\(\)/)
  assert.match(source, /const started = await realtime\.startRecording\(\)/)
  assert.match(source, /backendRecordingStartRef/)
  assert.match(source, /realtime\.cancelRecording\(\)/)
  assert.match(source, /aria-pressed=\{continuousVoiceActive\}/)
  assert.match(source, /avatarSpeaking \|\| realtime\.state\.phase !== 'idle'/)
  assert.match(home, /realtimeAssistant/)
  assert.match(home, /onSpeakingChange=\{setAvatarSpeaking\}/)
  assert.match(home, /onReadyChange=\{setAvatarReady\}/)
})

test('avatar readiness is propagated from the SDK runtime to the conversation gate', async () => {
  const stage = await readFile(fileURLToPath(new URL('../src/features/avatar/components/AvatarStage.tsx', import.meta.url)), 'utf8')
  const runtime = await readFile(fileURLToPath(new URL('../src/features/avatar/runtime/AvatarRuntimeSurface.tsx', import.meta.url)), 'utf8')
  assert.match(stage, /onReadyChange\?: \(ready: boolean\) => void/)
  assert.match(stage, /onReadyChange=\{onReadyChange\}/)
  assert.match(runtime, /onReadyChange\?\.\(next\.phase === 'ready' \|\| next\.phase === 'speaking'\)/)
  assert.match(runtime, /onReadyChange\?\.\(false\)/)
})

// runtime.ts imports sibling modules, so it cannot be loaded through a data
// URL. The adaptive wait is a pure function of two levels, so evaluate just
// that function body and leave the module graph alone.
const runtimeSource = await readFile(fileURLToPath(new URL('../src/features/realtime/runtime.ts', import.meta.url)), 'utf8')
const runtimeOutput = ts.transpileModule(runtimeSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
}).outputText

const adaptiveWaitSource = (() => {
  const start = runtimeOutput.indexOf('function endOfTurnSilenceMs')
  assert.ok(start >= 0, 'endOfTurnSilenceMs is missing from the runtime')
  const body = runtimeOutput.slice(start)
  const end = body.indexOf('\n}')
  assert.ok(end > 0, 'endOfTurnSilenceMs body is malformed')
  const constants = runtimeOutput.match(/const (SILENCE_WINDOW_\w+_MS|QUIET_ENDING_LEVEL) = [\d.]+/g)
  assert.ok(constants, 'adaptive wait constants are missing')
  return `${constants.join('\n')}\n${body.slice(0, end + 2)}\nreturn endOfTurnSilenceMs;`
})()

const endOfTurnSilenceMs = new Function(adaptiveWaitSource)()

test('end-of-turn wait shrinks for a decisive finish and stays bounded for a soft one', () => {
  const decisive = endOfTurnSilenceMs(0.4, 0.04)
  const soft = endOfTurnSilenceMs(0.05, 0.05)
  const moderate = endOfTurnSilenceMs(0.15, 0.1)

  // A loud finish that drops straight to silence is the clearest "I am done".
  assert.equal(decisive, 320)
  assert.ok(decisive < 650, 'a decisive finish must beat the flat window')
  // A quiet speaker may just be pausing mid-sentence; do not cut them off.
  assert.equal(soft, 650)
  assert.equal(moderate, 500)
  // Every branch has to stay inside the band so behaviour is predictable.
  for (const value of [decisive, soft, moderate, endOfTurnSilenceMs(0, 0), endOfTurnSilenceMs(1, 1)]) {
    assert.ok(value >= 320 && value <= 650, `wait ${value} escaped the adaptive band`)
  }
})

test('the opening speech segment is released far earlier than later ones', async () => {
  const speechSource = await readFile(fileURLToPath(new URL('../src/features/avatar/runtime/mofaRuntime.ts', import.meta.url)), 'utf8')
  const speechOutput = ts.transpileModule(speechSource, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
  }).outputText

  // The opening threshold must be strictly smaller, otherwise the avatar still
  // waits for a full clause before it starts talking.
  const opening = speechOutput.match(/const OPENING_SPEECH_MIN_CHARS = (\d+)/)
  const steady = speechOutput.match(/const STEADY_SPEECH_MIN_CHARS = (\d+)/)
  assert.ok(opening, 'opening threshold is missing')
  assert.ok(steady, 'steady threshold is missing')
  assert.ok(
    Number(opening[1]) < Number(steady[1]),
    `opening threshold ${opening[1]} must be smaller than steady ${steady[1]}`,
  )
  assert.match(speechOutput, /findSpeechBoundary\(this\.speechBuffer, flush, !this\.streamStarted\)/)
})

test('a comma ends a clause so speech starts without waiting for a full stop', async () => {
  const speechSource = await readFile(fileURLToPath(new URL('../src/features/avatar/runtime/mofaRuntime.ts', import.meta.url)), 'utf8')
  // The boundary punctuation class must include the comma, which is how people
  // actually pace Chinese speech.
  assert.match(speechSource, /const punctuation = \/\[[^\]]*，,[^\]]*\]\/g/)
})

