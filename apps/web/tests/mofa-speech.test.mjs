import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import * as ts from 'typescript'

const sourcePath = fileURLToPath(new URL('../src/features/avatar/runtime/mofaSpeech.ts', import.meta.url))
const source = await readFile(sourcePath, 'utf8')
const output = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
}).outputText
const moduleUrl = `data:text/javascript;base64,${Buffer.from(output).toString('base64')}`
const { buildMofaSpeechRequest } = await import(moduleUrl)

test('builds valid SSML and maps the vendor emotion field', () => {
  const request = buildMofaSpeechRequest(' 你好 <世界> ', { expression: 'happy' })
  assert.equal(request.ssml, '<speak>你好 &lt;世界&gt;</speak>')
  assert.deepEqual(request.extra, { emotion: 'happy' })
})

test('maps only documented actions so an unknown cue cannot break speech synthesis', () => {
  const supported = buildMofaSpeechRequest('三个重点', { expression: 'speaking', action: 'KeyPoints' })
  assert.match(supported.ssml, /<type>ka<\/type>/)
  assert.match(supported.ssml, /<action_semantic>KeyPoints<\/action_semantic>/)

  const unknown = buildMofaSpeechRequest('继续播报', { expression: 'speaking', gesture: 'small_nod' })
  assert.equal(unknown.ssml, '<speak>继续播报</speak>')
})

test('maps agent semantic aliases to the documented action intent catalog', () => {
  const greeting = buildMofaSpeechRequest('你好', { expression: 'happy', gesture: 'wave_hand', action: 'greet' })
  assert.match(greeting.ssml, /<type>ka_intent<\/type>/)
  assert.match(greeting.ssml, /<ka_intent>Hello<\/ka_intent>/)

  const nod = buildMofaSpeechRequest('明白了', { expression: 'acknowledging', gesture: 'nod' })
  assert.match(nod.ssml, /<ka_intent>Approve<\/ka_intent>/)
})

test('streams avatar sentence chunks without reopening every sentence', async () => {
  const runtime = await readFile(fileURLToPath(new URL('../src/features/avatar/runtime/mofaRuntime.ts', import.meta.url)), 'utf8')
  assert.match(runtime, /private streamStarted = false/)
  assert.match(runtime, /this\.avatar\.speak\(request\.ssml, isStart, isEnd, extra\)/)
  assert.match(runtime, /const isEnd = this\.speechFlushRequested && this\.speechQueue\.length === 0/)
  assert.match(runtime, /if \(!this\.speechFlushRequested && this\.speechQueue\.length === 1 && !this\.speechBuffer\.trim\(\)\) break/)
  assert.match(runtime, /await withTimeout\(initPromise, 60_000\)/)
  assert.match(runtime, /await waitForStablePaint\(\)/)
  assert.doesNotMatch(runtime, /Promise\.race\(\[initPromise, firstFrame\]\)/)
  assert.match(runtime, /this\.speechQueue\.length && this\.canDrainSpeechQueue\(\)/)
  assert.match(runtime, /return this\.speechFlushRequested \|\| this\.speechQueue\.length > 1 \|\| Boolean\(this\.speechBuffer\.trim\(\)\)/)
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
