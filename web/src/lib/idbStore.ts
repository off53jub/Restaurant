import { openDB, type IDBPDatabase } from 'idb'
import type { Visit } from './types'

const DB_NAME = 'restaurant-pwa'
const DB_VERSION = 1

type Meta = {
  key: string
  value: unknown
}

let dbPromise: Promise<IDBPDatabase> | null = null

function getDb(): Promise<IDBPDatabase> {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains('shops-db')) {
          db.createObjectStore('shops-db')
        }
        if (!db.objectStoreNames.contains('meta')) {
          db.createObjectStore('meta', { keyPath: 'key' })
        }
        if (!db.objectStoreNames.contains('visits')) {
          const s = db.createObjectStore('visits', { keyPath: 'id', autoIncrement: true })
          s.createIndex('shop_id', 'shop_id')
          s.createIndex('visited_at', 'visited_at')
        }
      }
    })
  }
  return dbPromise
}

export async function putShopsDb(buf: Uint8Array): Promise<void> {
  const db = await getDb()
  await db.put('shops-db', buf, 'blob')
}

export async function getShopsDb(): Promise<Uint8Array | null> {
  const db = await getDb()
  const v = await db.get('shops-db', 'blob')
  return v ?? null
}

export async function setMeta(key: string, value: unknown): Promise<void> {
  const db = await getDb()
  await db.put('meta', { key, value } as Meta)
}

export async function getMeta<T = unknown>(key: string): Promise<T | null> {
  const db = await getDb()
  const v = await db.get('meta', key)
  return (v?.value as T) ?? null
}

export async function addVisit(v: Visit): Promise<number> {
  const db = await getDb()
  return (await db.add('visits', v)) as number
}

export async function listVisits(): Promise<Visit[]> {
  const db = await getDb()
  return (await db.getAll('visits')) as Visit[]
}

export async function deleteVisit(id: number): Promise<void> {
  const db = await getDb()
  await db.delete('visits', id)
}
