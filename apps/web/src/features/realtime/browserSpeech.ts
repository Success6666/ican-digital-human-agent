export interface BrowserSpeechResult {
  isFinal: boolean
  transcript: string
}

export interface BrowserSpeechRecognition {
  lang: string
  interimResults: boolean
  continuous: boolean
  onresult: ((event: { resultIndex?: number; results: ArrayLike<{ isFinal: boolean; 0?: { transcript?: string } }> }) => void) | null
  onerror: ((event: { error?: string }) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

interface SpeechRecognitionWindow extends Window {
  SpeechRecognition?: new () => BrowserSpeechRecognition
  webkitSpeechRecognition?: new () => BrowserSpeechRecognition
}

export function browserSpeechSupported(): boolean {
  if (typeof window === 'undefined') return false
  const target = window as SpeechRecognitionWindow
  return Boolean(target.SpeechRecognition || target.webkitSpeechRecognition)
}

export function createBrowserSpeechRecognition(language = 'zh-CN'): BrowserSpeechRecognition | null {
  if (typeof window === 'undefined') return null
  const target = window as SpeechRecognitionWindow
  const Constructor = target.SpeechRecognition || target.webkitSpeechRecognition
  if (!Constructor) return null
  const recognition = new Constructor()
  recognition.lang = language
  recognition.interimResults = true
  recognition.continuous = false
  return recognition
}

export function readBrowserSpeechResults(event: { resultIndex?: number; results: ArrayLike<{ isFinal: boolean; 0?: { transcript?: string } }> }): BrowserSpeechResult[] {
  const results: BrowserSpeechResult[] = []
  const start = Math.max(0, event.resultIndex ?? 0)
  for (let index = start; index < event.results.length; index += 1) {
    const item = event.results[index]
    if (!item) continue
    const transcript = String(item[0]?.transcript ?? '').trim()
    if (transcript) results.push({ isFinal: Boolean(item.isFinal), transcript })
  }
  return results
}
