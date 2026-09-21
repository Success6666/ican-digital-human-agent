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

test('home session creation uses the selected provider instead of the server fallback', () => {
  assert.match(avatarModelSource, /const requestedProvider = provider \?\? selectedProvider/)
  assert.match(avatarModelSource, /avatarApi\.createSession\(requestedProvider\)/)
})

test('assistant speech only uses real response text', () => {
  assert.equal(homeSource.includes('message.content.trim() || message.statusText?.trim()'), true)
  assert.equal(homeSource.includes("text: latestAssistant.content || latestAssistant.statusText || ''"), true)
  assert.equal(homeSource.includes('pending: latestAssistant.content ? latestAssistant.pending : false'), true)
  assert.equal(homeSource.includes('我先理解一下你的意思'), false)
  // The interrupt key names the user turn, never the avatar's own state.
  // Deriving it from `avatarSpeaking` made it flip the instant a reply began,
  // so the stage stopped the answer it had just started and threw away the
  // opening sentence every time.
  //
  // It has to watch both doors a turn can come through. Keying on the chat
  // message alone meant a spoken turn — which never enters `chat.messages` —
  // could not interrupt at all, and any earlier text message kept outranking
  // every later utterance, so barge-in stayed dead for the rest of the session.
  assert.equal(
    homeSource.includes("const avatarInterruptKey = [latestUser?.id ?? '', realtime.state.utteranceId ?? ''].join('|')"),
    true,
  )
  assert.match(homeSource, /interruptKey=\{avatarInterruptKey\}/)
  assert.doesNotMatch(homeSource, /interruptKey=\{avatarSpeaking/)
})

test('conversation history is account scoped, bounded, and included as request context', () => {
  assert.match(conversationStoreSource, /STORAGE_PREFIX = 'digital-human:chat-history:v1:'/)
  assert.match(conversationStoreSource, /MAX_CONVERSATIONS = 40/)
  assert.match(chatModelSource, /useChat\(session: AvatarSession \| null, accountId\?: string\)/)
  assert.match(chatModelSource, /slice\(-MAX_CONTEXT_MESSAGES\)/)
  assert.match(chatModelSource, /streamChat\(\{ sessionId, message, history \}/)
})

test('filler events never become visible assistant text', () => {
  const fillerBranch = presenterSource.slice(presenterSource.indexOf("if (kind === 'filler')"), presenterSource.indexOf("if (kind === 'intent')"))
  assert.doesNotMatch(fillerBranch, /updateAssistant\([^\n]*statusText/)
})

test('voice turns land in the conversation record', async () => {
  // The realtime channel has always carried the final transcript and the reply
  // deltas, but nothing ever handed them to the chat model: the drawer showed no
  // spoken turn and the agent context built from `chat.messages` lost the whole
  // voice conversation. The options were declared and plumbed through the
  // runtime — the only missing piece was the app wiring them.
  const appSource = await readFile(fileURLToPath(new URL('../src/app/AuthenticatedApp.tsx', import.meta.url)), 'utf8')
  assert.match(appSource, /onTranscript: \(text\) => chat\.beginVoiceTurn\(text\)/)
  assert.match(appSource, /onAssistantText: \(text, append\) => chat\.appendVoiceAssistant\(text, append\)/)
  // The finalizer must be edge-triggered on leaving thinking/speaking, not run
  // on every idle render, or the pending placeholder is cleared before the
  // first delta arrives.
  assert.match(appSource, /previous !== 'idle' && realtime\.state\.phase === 'idle'/)
  assert.match(appSource, /chat\.finishVoiceTurn\(\)/)

  // The chat model owns the placeholder lifecycle: begin finalizes any turn
  // that is still open, append only reaches the tracked message, and clear and
  // newConversation reset the ref so a later run cannot append onto a cleared
  // history.
  assert.match(chatModelSource, /const beginVoiceTurn = useCallback/)
  assert.match(chatModelSource, /const appendVoiceAssistant = useCallback/)
  assert.match(chatModelSource, /const finishVoiceTurn = useCallback/)
  assert.match(chatModelSource, /voiceAssistantIdRef\.current = null/)
  assert.doesNotMatch(chatModelSource, /beginVoiceTurn\(text: string\)[\s\S]{0,400}interruptRef/)
})
