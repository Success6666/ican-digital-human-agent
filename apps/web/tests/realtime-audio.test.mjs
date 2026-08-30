import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import * as ts from 'typescript'

const sourcePath = fileURLToPath(new URL('../src/features/realtime/audioLifecycle.ts', import.meta.url))
const source = await readFile(sourcePath, 'utf8')
const output = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
}).outputText
const moduleUrl = `data:text/javascript;base64,${Buffer.from(output).toString('base64')}`
const { decideAudioEnd } = await import(moduleUrl)

test('audio_end clears the active generation even when transport is unavailable', () => {
  const active = { utteranceId: 'utt-1', revision: 3 }
  assert.deepEqual(decideAudioEnd(active, active, false), { accepted: true, shouldSend: false })
})

test('audio_end cannot close a different generation', () => {
  const active = { utteranceId: 'utt-1', revision: 3 }
  assert.deepEqual(decideAudioEnd(active, { utteranceId: 'utt-2', revision: 3 }, true), { accepted: false, shouldSend: false })
  assert.deepEqual(decideAudioEnd(active, { utteranceId: 'utt-1', revision: 4 }, true), { accepted: false, shouldSend: false })
})
