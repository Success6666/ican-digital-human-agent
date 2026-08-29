/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_AUTH_TARGET?: string
  readonly VITE_PORT?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
