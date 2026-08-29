const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '')
const TOKEN_KEY = 'digital-human-agent.token'

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
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
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
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: buildHeaders(init.headers),
  })
  const data = await parseBody(response)
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new CustomEvent('auth:expired'))
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
    body: body === undefined ? undefined : JSON.stringify(body),
  }),
  delete: <T>(path: string, init?: RequestInit) => request<T>(path, { ...init, method: 'DELETE' }),
}

export { API_BASE }
