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

test('continuous voice reads the latest session after asynchronous session creation', async () => {
  const source = await readFile(fileURLToPath(new URL('../src/features/chat/components/HomeConversationBar.tsx', import.meta.url)), 'utf8')
  assert.match(source, /sessionRef\.current\s*=\s*session/)
  assert.match(source, /if \(!sessionRef\.current\)/)
  assert.match(source, /onSendRef\.current\(finalText\)/)
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
  assert.match(source, /realtime\.cancelRecording\(\)/)
  assert.match(source, /aria-pressed=\{continuousVoiceActive\}/)
  assert.match(source, /avatarSpeaking \|\| realtime\.state\.phase !== 'idle'/)
  assert.match(home, /realtimeAssistant/)
  assert.match(home, /onSpeakingChange=\{setAvatarSpeaking\}/)
})
