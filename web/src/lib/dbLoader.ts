import pako from 'pako'
import type { Database } from 'sql.js'
import { openDatabase } from './sqlite'
import { getMeta, getShopsDb, putShopsDb, setMeta } from './idbStore'

export type LoadProgress =
  | { phase: 'cache-hit' }
  | { phase: 'download'; received: number; total: number | null }
  | { phase: 'decompress' }
  | { phase: 'persist' }
  | { phase: 'open' }
  | { phase: 'ready' }
  | { phase: 'error'; error: Error }

export type DbSourceConfig = {
  url: string
  version: string
}

export async function loadDb(
  source: DbSourceConfig,
  onProgress: (p: LoadProgress) => void
): Promise<Database> {
  try {
    const storedVersion = await getMeta<string>('db_version')
    if (storedVersion === source.version) {
      const buf = await getShopsDb()
      if (buf) {
        onProgress({ phase: 'cache-hit' })
        onProgress({ phase: 'open' })
        const db = await openDatabase(buf)
        onProgress({ phase: 'ready' })
        return db
      }
    }

    const res = await fetch(source.url)
    if (!res.ok) throw new Error(`Failed to fetch DB: ${res.status} ${res.statusText}`)

    const totalHeader = res.headers.get('content-length')
    const total = totalHeader ? parseInt(totalHeader, 10) : null

    const reader = res.body?.getReader()
    if (!reader) throw new Error('No response body')

    const chunks: Uint8Array[] = []
    let received = 0
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      chunks.push(value)
      received += value.byteLength
      onProgress({ phase: 'download', received, total })
    }

    onProgress({ phase: 'decompress' })
    const gz = new Uint8Array(received)
    {
      let offset = 0
      for (const c of chunks) {
        gz.set(c, offset)
        offset += c.byteLength
      }
    }
    const dbBytes = pako.ungzip(gz)

    onProgress({ phase: 'persist' })
    await putShopsDb(dbBytes)
    await setMeta('db_version', source.version)

    onProgress({ phase: 'open' })
    const db = await openDatabase(dbBytes)
    onProgress({ phase: 'ready' })
    return db
  } catch (e) {
    const err = e instanceof Error ? e : new Error(String(e))
    onProgress({ phase: 'error', error: err })
    throw err
  }
}
