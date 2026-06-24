import type { DbSourceConfig } from './dbLoader'

export const DB_SOURCE: DbSourceConfig = {
  url:
    (import.meta.env.VITE_DB_URL as string | undefined) ??
    `${import.meta.env.BASE_URL}shops-web.db.gz`,
  version: (import.meta.env.VITE_DB_VERSION as string | undefined) ?? 'phase-e'
}
