import type { AvatarPreview } from './previewCache'

interface AvatarPreviewSurfaceProps {
  preview: AvatarPreview
}

export function AvatarPreviewSurface({ preview }: AvatarPreviewSurfaceProps) {
  return (
    <div
      className="avatar-preview-surface"
      style={{
        backgroundImage: preview.backgroundImage,
        backgroundColor: preview.backgroundColor || 'transparent',
      }}
      aria-label="数字人静态预览"
    >
      <img src={preview.avatarDataUrl} alt="" />
      {preview.foregroundImage && <div className="avatar-preview-foreground" style={{ backgroundImage: preview.foregroundImage }} aria-hidden="true" />}
    </div>
  )
}
