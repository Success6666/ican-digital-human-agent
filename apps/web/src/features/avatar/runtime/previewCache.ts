const STORAGE_KEY = 'ican.avatar.preview.v4'
const UPDATED_EVENT = 'ican-avatar-preview-updated'

export interface AvatarPreview {
  provider: string
  avatarDataUrl: string
  backgroundImage?: string
  foregroundImage?: string
  backgroundSize?: string
  backgroundPosition?: string
  backgroundColor?: string
  savedAt: string
}

export function readAvatarPreview(): AvatarPreview | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const value = JSON.parse(raw) as Partial<AvatarPreview>
    if (typeof value.provider !== 'string' || typeof value.avatarDataUrl !== 'string') return null
    return value as AvatarPreview
  } catch {
    return null
  }
}

export function saveAvatarPreview(host: HTMLElement, provider: string): AvatarPreview | null {
  const canvas = host.querySelector('canvas')
  if (!canvas || canvas.width < 2 || canvas.height < 2) return null
  const background = host.querySelector<HTMLElement>('#avatar-bg-container')
  const style = background ? getComputedStyle(background) : undefined
  const backgroundImages = [...new Set(performance.getEntriesByType('resource')
    .map((entry) => entry.name)
    .filter((url) => /background_2D\/.*\.png(?:\?|$)/i.test(url)))]
  const baseImage = backgroundImages.find((url) => !/__desk\.png(?:\?|$)/i.test(url))
  const foregroundImage = backgroundImages.find((url) => /__desk\.png(?:\?|$)/i.test(url))
  const preview: AvatarPreview = {
    provider,
    avatarDataUrl: canvas.toDataURL('image/webp', 0.84),
    backgroundImage: baseImage
      ? `url("${baseImage}")`
      : style?.backgroundImage && style.backgroundImage !== 'none' ? style.backgroundImage : undefined,
    foregroundImage: foregroundImage ? `url("${foregroundImage}")` : undefined,
    backgroundSize: style?.backgroundSize,
    backgroundPosition: style?.backgroundPosition,
    backgroundColor: style?.backgroundColor,
    savedAt: new Date().toISOString(),
  }
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preview))
    window.dispatchEvent(new CustomEvent(UPDATED_EVENT))
  } catch {
    return null
  }
  return preview
}

export function subscribeAvatarPreview(listener: () => void): () => void {
  const onUpdate = () => listener()
  window.addEventListener(UPDATED_EVENT, onUpdate)
  window.addEventListener('storage', onUpdate)
  return () => {
    window.removeEventListener(UPDATED_EVENT, onUpdate)
    window.removeEventListener('storage', onUpdate)
  }
}
