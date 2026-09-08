import type { AvatarPerformanceCue } from '../../../shared/api/types'

export const MOFA_EMOTIONS = ['happy', 'sad', 'angry', 'surprised', 'neutral'] as const

const officialEmotions = new Set<string>(MOFA_EMOTIONS)
const internalEmotionMap: Record<string, string> = {
  relieved: 'happy',
  speaking: 'neutral',
  listening: 'neutral',
  thinking: 'neutral',
  acknowledging: 'neutral',
  interrupted: 'neutral',
}

export interface MofaSpeechRequest {
  ssml: string
  extra: Record<string, unknown>
}

export function buildMofaSpeechRequest(text: string, cue?: AvatarPerformanceCue, options?: { enableEmotion?: boolean }): MofaSpeechRequest {
  const clean = text.trim()
  const actionEvent = actionSsml(cue?.action) || actionSsml(cue?.gesture)
  const emotion = options?.enableEmotion ? normalizeEmotion(cue?.expression) : undefined
  return {
    ssml: `<speak>${actionEvent}${escapeXml(clean)}</speak>`,
    extra: emotion ? { emotion } : {},
  }
}

export const MOFA_ACTION_INTENTS = [
  'FistSalute', 'ClapHands', 'Welcome', 'ThankYou', 'Prohibit', 'KeyPoints', 'Stable', 'Comfort',
  'Downsize', 'Cuttime', 'Extendsize', 'Extendtime', 'Elevate', 'Like', 'Goodbye', 'Hello',
  'PointingSelf', 'Surprise', 'Pointscreen', 'Wish', 'Heart', 'PointAudience', 'Downward', 'Click',
  'Encourage', 'Wave', 'Up', 'Down', 'Left', 'Right', 'Forward', 'Backward', 'Center', 'Near', 'Far',
  'Large', 'Small', 'High', 'Low', 'Partial', 'Whole', 'Edge', 'Apologize', 'Approve', 'Pause',
  'Expect', 'Think', 'Confused', 'Indifferent', 'Ecstasy', 'Joyful', 'Playful', 'Dissatisfied',
  'Reject', 'Worry', 'Disappointed', 'Aggrieved', 'Shakehands', 'Highfive', 'Curious', 'Worship',
  'Shy', 'Scared', 'Tired', 'Surprised', 'Nauseous', 'Ill', 'Dance', 'Scan', 'Sos',
] as const

const actionIntents: Record<string, string> = Object.fromEntries(
  MOFA_ACTION_INTENTS.map((name) => [name.toLowerCase(), name]),
)

function actionSsml(value: unknown): string {
  const semantic = normalizeSemantic(value)
  if (!semantic) return ''
  const intent = actionIntents[semantic.toLowerCase()]
  if (intent) return `<ue4event><type>ka_intent</type><data><ka_intent>${intent}</ka_intent></data></ue4event>`
  return ''
}

function normalizeEmotion(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = value.trim().toLowerCase()
  if (officialEmotions.has(normalized)) return normalized
  return internalEmotionMap[normalized]
}

function normalizeSemantic(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const clean = value.trim()
  if (!clean || !/^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/.test(clean)) return undefined
  return clean
}

function escapeXml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}
