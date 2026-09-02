import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const source = await readFile(fileURLToPath(new URL('../src/features/chat/components/HomeConversationBar.tsx', import.meta.url)), 'utf8')
const homeSource = await readFile(fileURLToPath(new URL('../src/pages/HomePage.tsx', import.meta.url)), 'utf8')
const chatModelSource = await readFile(fileURLToPath(new URL('../src/features/chat/model.ts', import.meta.url)), 'utf8')
const avatarModelSource = await readFile(fileURLToPath(new URL('../src/features/avatar/model.ts', import.meta.url)), 'utf8')
const conversationStoreSource = await readFile(fileURLToPath(new URL('../src/features/chat/conversationStore.ts', import.meta.url)), 'utf8')
const presenterSource = await readFile(fileURLToPath(new URL('../src/features/chat/streamEventPresenter.ts', import.meta.url)), 'utf8')

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
  assert.match(avatarModelSource, /createInFlightRef\.current/)
  assert.match(avatarModelSource, /if \(createInFlightRef\.current\) return createInFlightRef\.current/)
})

test('assistant speech only uses real response text', () => {
  assert.equal(homeSource.includes('message.content.trim() || message.statusText?.trim()'), true)
  assert.equal(homeSource.includes("text: latestAssistant.content || latestAssistant.statusText || ''"), true)
  assert.equal(homeSource.includes('pending: latestAssistant.content ? latestAssistant.pending : false'), true)
  assert.equal(homeSource.includes('我先理解一下你的意思'), false)
  assert.match(homeSource, /interruptKey=\{avatarSpeaking \? latestUser\?\.id : undefined\}/)
})

test('conversation history is account scoped, bounded, and included as request context', () => {
  assert.match(conversationStoreSource, /STORAGE_PREFIX = 'ican:chat-history:v1:'/)
  assert.match(conversationStoreSource, /MAX_CONVERSATIONS = 40/)
  assert.match(chatModelSource, /useChat\(session: AvatarSession \| null, accountId\?: string\)/)
  assert.match(chatModelSource, /slice\(-MAX_CONTEXT_MESSAGES\)/)
  assert.match(chatModelSource, /streamChat\(\{ sessionId, message, history \}/)
})

test('filler events never become visible assistant text', () => {
  const fillerBranch = presenterSource.slice(presenterSource.indexOf("if (kind === 'filler')"), presenterSource.indexOf("if (kind === 'intent')"))
  assert.doesNotMatch(fillerBranch, /updateAssistant\([^\n]*statusText/)
})
