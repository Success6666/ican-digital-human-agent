export function formatTime(value: string | number | Date): string {
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return '--:--'
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(date)
}

export function formatExpiry(value?: string): string {
  if (!value) return '未提供过期时间'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '过期时间未知'
  return `有效至 ${new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(date)}`
}

/** Remove credentials and internal identifiers before text reaches the UI. */
export function sanitizeDisplayText(value: string, limit = 180): string {
  const sanitized = value
    .replace(/(api[_-]?key|secret(?:[_-]?key)?|token|password|authorization)\s*[:=]\s*[^\s,;]+/gi, '$1：已隐藏')
    .replace(/\b(?:bearer|basic)\s+[a-z0-9._~+/=-]+/gi, '凭证已隐藏')
    .replace(/\b(?:trace|span|parent[_-]?span|session|user)[_-]?id\s*[:=]\s*[^\s,;}\]]+/gi, '内部标识：已隐藏')
    .replace(/\b[0-9a-f]{24,}\b/gi, '内部标识已隐藏')
    .replace(/\b[0-9a-f]{8}-[0-9a-f-]{27,}\b/gi, '内部标识已隐藏')
  return sanitized.length > limit ? `${sanitized.slice(0, Math.max(0, limit - 1))}…` : sanitized
}

export function stringifyDetail(value: unknown): string {
  if (value === undefined || value === null) return ''
  if (typeof value === 'string') return sanitizeDisplayText(value)
  try {
    return sanitizeDisplayText(JSON.stringify(value, null, 2))
  } catch {
    return sanitizeDisplayText(String(value))
  }
}
