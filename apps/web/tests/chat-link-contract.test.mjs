import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const source = await readFile(fileURLToPath(new URL('../src/features/chat/components/HomeConversationBar.tsx', import.meta.url)), 'utf8')

test('text chat does not wait for the realtime websocket', () => {
  assert.match(source, /if \(!session\) \{[\s\S]*?onCreateSession\(message\)[\s\S]*?\} else \{[\s\S]*?onSend\(message\)/)
  assert.doesNotMatch(source, /else if \(ready\) onSend\(message\)/)
  assert.doesNotMatch(source, /disabled=\{Boolean\(session\) && !ready\}/)
})

test('session creation is guarded while the provider session is being created', () => {
  assert.match(source, /isCreating\?: boolean/)
  assert.match(source, /if \(isCreating\) return/)
  assert.match(source, /disabled=\{!draft\.trim\(\) \|\| \(!session && isCreating\)\}/)
})
