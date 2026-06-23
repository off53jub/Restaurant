/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

interface ImportMetaEnv {
  readonly VITE_DB_URL?: string
  readonly VITE_DB_VERSION?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
