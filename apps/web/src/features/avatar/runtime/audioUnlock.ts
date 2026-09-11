/**
 * Mobile audio unlock for the avatar runtime.
 *
 * The Mofa SDK renders the avatar into a WebGL canvas and pipes TTSA audio
 * through WebAudio. Desktop browsers usually start an AudioContext in the
 * `running` state, but iOS Safari and mobile Chrome start it `suspended` and
 * only leave that state when audio is played from inside a real user gesture.
 * Nothing in the speak path ever did that, so on a phone every utterance was
 * rendered silently: the avatar moved its mouth and no sound came out, while
 * the same build was fine on a desktop.
 *
 * Unlocking is per-AudioContext, and the SDK creates its own context that we
 * never get a reference to. So this module does two things: keep the page-level
 * unlock (a context of our own, resumed in a gesture) and track every context
 * created afterwards, including the SDK's, so a gesture can resume those too.
 */

interface AudioContextConstructorLike {
  new (options?: AudioContextOptions): AudioContext
  prototype: unknown
}

/**
 * `window` is typed `Window & typeof globalThis`, and `AudioContext` only comes
 * from the `globalThis` half. Modelling the two constructors as an interface
 * keeps the assertion from dropping it, and covers the legacy webkit name.
 */
interface WindowWithAudioConstructors {
  AudioContext?: AudioContextConstructorLike
  webkitAudioContext?: AudioContextConstructorLike
}

const trackedContexts = new Set<AudioContext>()
let sharedContext: AudioContext | undefined
let trackerInstalled = false
let gestureBound = false

export interface AvatarAudioState {
  /** State of the context this module owns; `unsupported` when WebAudio is absent. */
  state: AudioContextState | 'unsupported'
  /** True once audio has actually been resumed from a user gesture. */
  unlocked: boolean
  /** Contexts created on the page, including the vendor SDK's own. */
  trackedCount: number
}

export function avatarAudioState(): AvatarAudioState {
  if (sharedContext && sharedContext.state !== 'closed') {
    return {
      state: sharedContext.state,
      unlocked: sharedContext.state === 'running',
      trackedCount: trackedContexts.size,
    }
  }
  // No context of our own yet: the page has not been unlocked, which on a
  // phone means audio is still suspended and silence is expected.
  const supported = Boolean(getAudioContextConstructor())
  return { state: supported ? 'suspended' : 'unsupported', unlocked: false, trackedCount: trackedContexts.size }
}

/**
 * Resume audio. Must run inside a user gesture to have any effect on mobile;
 * calling it from a timer or a websocket callback will be ignored by the
 * browser and is silently downgraded to "still suspended".
 */
export async function unlockAvatarAudio(): Promise<AvatarAudioState> {
  const Constructor = getAudioContextConstructor()
  if (!Constructor) return { state: 'unsupported', unlocked: false, trackedCount: 0 }
  try {
    if (!sharedContext || sharedContext.state === 'closed') {
      sharedContext = new Constructor()
      trackedContexts.add(sharedContext)
    }
    const context = sharedContext
    // Start the silent source *before* awaiting anything: iOS only counts
    // audio as "played in a gesture" while the gesture is still being handled,
    // and an `await` may hand control back to the event loop first.
    playSilentBuffer(context)
    if (context.state !== 'running') await context.resume().catch(() => undefined)
    // The SDK's context was created outside any gesture, so it stayed
    // suspended even after the page itself was unlocked.
    resumeTrackedAudio()
    return avatarAudioState()
  } catch {
    return avatarAudioState()
  }
}

/**
 * Best-effort resume for contexts that are already tracked.
 *
 * Speak is triggered by an inbound websocket delta, never by a gesture, so
 * this cannot unlock a phone on its own — it exists to recover a context that
 * a gesture already unlocked but that the browser suspended again (a background
 * tab, an incoming call, a route switch).
 */
export function resumeTrackedAudio(): void {
  for (const context of trackedContexts) {
    // A long session creates and discards contexts; dropping the closed ones
    // keeps this set from growing for the lifetime of the page.
    if (context.state === 'closed') {
      trackedContexts.delete(context)
      continue
    }
    if (context.state === 'suspended') void context.resume().catch(() => undefined)
  }
}

/**
 * Watch every AudioContext created from here on, so a later gesture can resume
 * the one the vendor SDK makes for itself. Falls back to doing nothing when the
 * constructor cannot be wrapped; a page-level unlock still has a chance then.
 */
export function installAudioContextTracker(): void {
  if (trackerInstalled || typeof window === 'undefined') return
  const scope = window as unknown as WindowWithAudioConstructors
  const Original = (scope.AudioContext ?? scope.webkitAudioContext) as AudioContextConstructorLike | undefined
  if (!Original) return

  function TrackedContext(this: unknown, options?: AudioContextOptions) {
    const context = new Original!(options)
    trackedContexts.add(context)
    return context
  }
  TrackedContext.prototype = Original.prototype
  const Wrapped = TrackedContext as unknown as AudioContextConstructorLike

  try {
    scope.AudioContext = Wrapped
    scope.webkitAudioContext = Wrapped
    trackerInstalled = true
  } catch {
    trackerInstalled = false
  }
}

/**
 * Unlock on the first gesture anywhere in the document.
 *
 * The avatar usually connects before the user touches anything, so waiting for
 * a click on the stage would miss the very gesture that could have unlocked
 * audio. Capture phase keeps this working when a child stops propagation.
 */
export function bindGestureAudioUnlock(): () => void {
  if (gestureBound || typeof document === 'undefined') return () => undefined
  gestureBound = true
  const events = ['pointerdown', 'mousedown', 'touchend', 'keydown'] as const
  const handler = () => { void unlockAvatarAudio() }
  for (const event of events) {
    document.addEventListener(event, handler, { capture: true, passive: true })
  }
  return () => {
    gestureBound = false
    for (const event of events) {
      document.removeEventListener(event, handler, { capture: true })
    }
  }
}

function playSilentBuffer(context: AudioContext): void {
  try {
    const buffer = context.createBuffer(1, 1, context.sampleRate)
    const source = context.createBufferSource()
    source.buffer = buffer
    source.connect(context.destination)
    source.start(0)
  } catch {
    // A failed silent buffer is not fatal: `resume()` may already be enough.
  }
}

function getAudioContextConstructor(): AudioContextConstructorLike | undefined {
  if (typeof window === 'undefined') return undefined
  const scope = window as unknown as WindowWithAudioConstructors
  return scope.AudioContext ?? scope.webkitAudioContext
}
