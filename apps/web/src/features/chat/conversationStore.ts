import type { ChatConversation, ChatMessage } from './model'

const STORAGE_PREFIX = 'digital-human:chat-history:v1:'
// 早期版本写入的前缀。仅用于读取兜底，避免改前缀后既有对话历史瞬间消失；
// 新数据一律写入上面的前缀，读到旧数据后会在下一次写入时自然迁移。
const LEGACY_STORAGE_PREFIX = 'ican:chat-history:v1:'
const MAX_CONVERSATIONS = 40
const MAX_MESSAGES = 200
const MAX_CONTENT_LENGTH = 20_000

function storageKey(accountId: string, prefix: string = STORAGE_PREFIX): string {
  return `${prefix}${encodeURIComponent(accountId.trim())}`
}

function cleanMessage(value: unknown): ChatMessage | null {
  if (!value || typeof value !== 'object') return null
  const item = value as Partial<ChatMessage>
  if (!item.id || !['user', 'assistant', 'system'].includes(String(item.role))) return null
  return {
    id: String(item.id).slice(0, 128),
    role: item.role as ChatMessage['role'],
    content: String(item.content ?? '').slice(0, MAX_CONTENT_LENGTH),
    createdAt: String(item.createdAt ?? new Date().toISOString()).slice(0, 64),
    pending: false,
    traceId: item.traceId ? String(item.traceId).slice(0, 128) : undefined,
    presentation: item.presentation,
  }
}

function cleanConversation(value: unknown): ChatConversation | null {
  if (!value || typeof value !== 'object') return null
  const item = value as Partial<ChatConversation>
  if (!item.id) return null
  const messages = Array.isArray(item.messages)
    ? item.messages.map(cleanMessage).filter((message): message is ChatMessage => Boolean(message)).slice(-MAX_MESSAGES)
    : []
  return {
    id: String(item.id).slice(0, 128),
    title: String(item.title || '新对话').slice(0, 48),
    createdAt: String(item.createdAt ?? new Date().toISOString()).slice(0, 64),
    updatedAt: String(item.updatedAt ?? item.createdAt ?? new Date().toISOString()).slice(0, 64),
    messages,
  }
}

export function createConversation(): ChatConversation {
  const now = new Date().toISOString()
  const randomId = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  return { id: `conversation-${randomId}`, title: '新对话', createdAt: now, updatedAt: now, messages: [] }
}

export function readConversations(accountId: string): ChatConversation[] {
  if (!accountId.trim()) return []
  try {
    const raw =
    window.localStorage.getItem(storageKey(accountId)) ??
    window.localStorage.getItem(storageKey(accountId, LEGACY_STORAGE_PREFIX))
    const parsed = raw ? JSON.parse(raw) : []
    if (!Array.isArray(parsed)) return []
    return parsed
      .map(cleanConversation)
      .filter((conversation): conversation is ChatConversation => Boolean(conversation))
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
      .slice(0, MAX_CONVERSATIONS)
  } catch {
    return []
  }
}

export function writeConversations(accountId: string, conversations: ChatConversation[]): void {
  if (!accountId.trim()) return
  const bounded = conversations
    .map(cleanConversation)
    .filter((conversation): conversation is ChatConversation => Boolean(conversation))
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
    .slice(0, MAX_CONVERSATIONS)
  try {
    window.localStorage.setItem(storageKey(accountId), JSON.stringify(bounded))
  } catch {
    // 历史记录达到浏览器配额时保留当前内存会话，不阻塞实时对话。
  }
}
