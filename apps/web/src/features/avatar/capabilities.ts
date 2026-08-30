const capabilityLabels: Record<string, string> = {
  text_input: '文本输入',
  audio_input: '语音输入',
  video_output: '视频输出',
  streaming: '流式输出',
  external_runtime: '外部运行时',
  interrupt: '支持中断',
}

const interruptScopeLabels: Record<string, string> = {
  run: '单轮中断',
  session: '会话中断',
  local: '本地隔离',
  unsupported: '不支持中断',
}

/** 将 Provider 能力对象转换为面向用户的短标签。 */
export function capabilityNames(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String)
  if (!value || typeof value !== 'object') return []
  return Object.entries(value as Record<string, unknown>).flatMap(([key, enabled]) => {
    const normalizedKey = key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)
    if (normalizedKey === 'interrupt_scope') {
      const scope = interruptScopeLabels[String(enabled)]
      return [scope ? `中断：${scope}` : `中断范围：${String(enabled)}`]
    }
    if (enabled === true) return [capabilityLabels[normalizedKey] ?? `支持${humanize(normalizedKey)}`]
    if (enabled === false || enabled == null) return []
    return [`${capabilityLabels[normalizedKey] ?? humanize(normalizedKey)}：${String(enabled)}`]
  })
}

function humanize(value: string): string {
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}
