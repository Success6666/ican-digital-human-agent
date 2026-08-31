const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '')
const LEGACY_TOKEN_KEY = 'digital-human-agent.token'
let sessionToken: string | null = null

export class ApiError extends Error {
  readonly status: number
  readonly data: unknown

  constructor(status: number, message: string, data?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

export function getToken(): string | null {
  return sessionToken
}

export function setToken(token: string): void {
  sessionToken = token
  localStorage.removeItem(LEGACY_TOKEN_KEY)
}

export function clearToken(): void {
  sessionToken = null
  localStorage.removeItem(LEGACY_TOKEN_KEY)
}

function buildHeaders(init?: HeadersInit): Headers {
  const headers = new Headers(init)
  const token = getToken()
  if (token) {
    headers.set('satoken', token)
    headers.set('Authorization', `Bearer ${token}`)
  }
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  headers.set('X-Client', 'digital-human-agent-web')
  return headers
}

async function parseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) {
    try {
      return await response.json()
    } catch {
      return undefined
    }
  }
  return response.text().catch(() => undefined)
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = String(init.method ?? 'GET').toUpperCase()
  const retryable = ['GET', 'HEAD', 'OPTIONS', 'DELETE'].includes(method)
  let response: Response | undefined
  let lastError: unknown
  for (let attempt = 0; attempt < (retryable ? 3 : 1); attempt += 1) {
    try {
      response = await fetch(`${API_BASE}${path}`, {
        ...init,
        credentials: 'include',
        headers: init.body instanceof FormData ? (() => { const headers = buildHeaders(init.headers); headers.delete('Content-Type'); return headers })() : buildHeaders(init.headers),
      })
      break
    } catch (cause) {
      lastError = cause
      if (init.signal?.aborted || attempt >= 2) throw cause
      await new Promise((resolve) => window.setTimeout(resolve, 180 * (attempt + 1)))
    }
  }
  if (!response) throw lastError instanceof Error ? lastError : new Error('网络请求失败')
  const data = await parseBody(response)
  if (!response.ok) {
    if (response.status === 401 && getToken()) window.dispatchEvent(new CustomEvent('auth:expired'))
    const message = typeof data === 'object' && data && 'message' in data
      ? String((data as { message: unknown }).message)
      : `请求失败（${response.status}）`
    throw new ApiError(response.status, message, data)
  }
  return data as T
}

export const api = {
  get: <T>(path: string, init?: RequestInit) => request<T>(path, { ...init, method: 'GET' }),
  post: <T>(path: string, body?: unknown, init?: RequestInit) => request<T>(path, {
    ...init,
    method: 'POST',
    body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
  }),
  patch: <T>(path: string, body?: unknown, init?: RequestInit) => request<T>(path, {
    ...init,
    method: 'PATCH',
    body: body === undefined ? undefined : JSON.stringify(body),
  }),
  delete: <T>(path: string, init?: RequestInit) => request<T>(path, { ...init, method: 'DELETE' }),
}

export { API_BASE }
