import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const source = await readFile(fileURLToPath(new URL('../src/features/chat/components/HomeConversationBar.tsx', import.meta.url)), 'utf8')
const homeSource = await readFile(fileURLToPath(new URL('../src/pages/HomePage.tsx', import.meta.url)), 'utf8')

test('text chat is gated by a ready digital-human runtime', () => {
  assert.match(source, /const interactionReady = Boolean\(session && avatarReady\)/)
  assert.match(source, /if \(!message \|\| !interactionReady \|\| isCreating\) return/)
  assert.match(source, /disabled=\{!interactionReady \|\| isCreating\}/)
  assert.doesNotMatch(source, /onCreateSession\(message\)/)
})

test('session creation is guarded while the provider session is being created', () => {
  assert.match(source, /isCreating\?: boolean/)
  assert.match(source, /isCreating\?: boolean/)
  assert.match(source, /if \(!message \|\| !interactionReady \|\| isCreating\) return/)
  assert.match(source, /disabled=\{!draft\.trim\(\) \|\| !interactionReady \|\| isCreating\}/)
})

test('assistant speech only uses real response text', () => {
  assert.equal(homeSource.includes('message.content.trim() || message.statusText?.trim()'), true)
  assert.equal(homeSource.includes("text: latestAssistant.content || latestAssistant.statusText || ''"), true)
  assert.equal(homeSource.includes('pending: latestAssistant.content ? latestAssistant.pending : false'), true)
  assert.equal(homeSource.includes('我先理解一下你的意思'), false)
})
