export function booleanCapability(value: unknown): boolean | undefined {
  if (typeof value === 'boolean') return value
  if (value === 'supported' || value === 'ready' || value === 'available') return true
  if (value === 'unsupported' || value === 'disabled' || value === 'unavailable') return false
  return undefined
}

export function isUnsupportedCapability(value: unknown): boolean {
  return value === false || value === 'unsupported' || value === 'disabled' || value === 'unavailable'
}
