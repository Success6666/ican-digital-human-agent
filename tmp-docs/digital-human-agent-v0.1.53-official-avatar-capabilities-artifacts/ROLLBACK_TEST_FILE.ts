import type { AvatarPerformanceCue } from '../../../shared/api/types'

const emotionMap: Record<string, string> = {
  happy: 'happy',
  relieved: 'happy',
  positive: 'happy',
  sad: 'sad',
  angry: 'angry',
  serious: 'angry',
  surprised: 'surprised',
  neutral: 'neutral',
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

export function buildMofaSpeechRequest(text: string, cue?: AvatarPerformanceCue): MofaSpeechRequest {
  const clean = text.trim()
  const actionEvent = actionSsml(cue?.action ?? cue?.gesture)
  const emotion = normalizeEmotion(cue?.expression)
  return {
    ssml: `<speak>${actionEvent}${escapeXml(clean)}</speak>`,
    extra: emotion ? { emotion } : {},
  }
}

const keyActions: Record<string, string> = {
  elevate: 'Elevate',
  keypoints: 'KeyPoints',
  key_points: 'KeyPoints',
  rightside02: 'RightSide02',
  right_side: 'RightSide02',
}

const actionIntentNames = [
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
  actionIntentNames.map((name) => [name.toLowerCase(), name]),
)

Object.assign(actionIntents, {
  greet: 'Hello',
  greeting: 'Hello',
  wave_hand: 'Wave',
  wavehand: 'Wave',
  nod: 'Approve',
  acknowledge: 'Approve',
  point_screen: 'Pointscreen',
  point_self: 'PointingSelf',
  point_audience: 'PointAudience',
  clap: 'ClapHands',
  thank_you: 'ThankYou',
  handshake: 'Shakehands',
  high_five: 'Highfive',
})

function actionSsml(value: unknown): string {
  const semantic = normalizeSemantic(value)
  if (!semantic) return ''
  const key = semantic.toLowerCase()
  const action = keyActions[key]
  if (action) return `<ue4event><type>ka</type><data><action_semantic>${action}</action_semantic></data></ue4event>`
  const intent = actionIntents[key]
  if (intent) return `<ue4event><type>ka_intent</type><data><ka_intent>${intent}</ka_intent></data></ue4event>`
  return ''
}

function normalizeEmotion(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  return emotionMap[value.trim().toLowerCase()] ?? 'neutral'
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
