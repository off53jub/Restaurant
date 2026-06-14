/**
 * End-to-end smoke test: load the real shops-web.db.gz from public/,
 * decompress it, hand it to sql.js, and run searchShops() with the
 * kaishoku preset. Verifies the full data pipeline outside the browser.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import pako from 'pako'
import initSqlJs from 'sql.js'
import { getReviewsByShopId, getShopById, searchShops } from '../src/lib/queryBuilder'

const DB_PATH = resolve(__dirname, '../public/shops-web.db.gz')

const skip = !existsSync(DB_PATH)

describe.skipIf(skip)('e2e: real DB + kaishoku preset', () => {
  it('runs the kaishoku preset against the real DB and returns plausible rows', async () => {
    const gz = readFileSync(DB_PATH)
    const dbBytes = pako.ungzip(gz)

    const SQL = await initSqlJs()
    const db = new SQL.Database(dbBytes)

    const result = searchShops(db, { preset: 'kaishoku', limit: 5 })
    expect(result.rows.length).toBeGreaterThan(0)
    expect(result.priceBand).toEqual([7500, 8800])
    expect(result.scene).toBe('kaishoku')

    for (const r of result.rows) {
      expect(r.fully_private_room).toBe(1)
      expect(r.mid_room_ok).toBe(1)
      expect(r.smoking_at_seat).toBe('allowed')
      expect(r.address).toMatch(/虎ノ門|新橋|赤坂|銀座|六本木|汐留|霞が関|内幸町|浜松町|西新橋|麻布|新富|築地|愛宕/)
      // Phase D: photo URL columns populated
      expect(r.photo_url_l).toMatch(/^https:\/\/imgfp\.hotp\.jp\//)
    }

    db.close()
  }, 60000)

  it('runs the date_shinjuku preset and returns Shinjuku-area rows', async () => {
    const gz = readFileSync(DB_PATH)
    const dbBytes = pako.ungzip(gz)

    const SQL = await initSqlJs()
    const db = new SQL.Database(dbBytes)

    const result = searchShops(db, { preset: 'date_shinjuku', limit: 3 })
    expect(result.rows.length).toBeGreaterThan(0)
    for (const r of result.rows) {
      expect(r.address).toMatch(/新宿|歌舞伎町|代々木|千駄ヶ谷|信濃町|四谷|四ツ谷|曙橋|市ヶ谷|中野坂上/)
      expect(r.atmosphere_calm ?? 0).toBeGreaterThanOrEqual(50)
    }

    db.close()
  }, 60000)

  it('getShopById + getReviewsByShopId surface reviews for a known shop', async () => {
    const gz = readFileSync(DB_PATH)
    const dbBytes = pako.ungzip(gz)

    const SQL = await initSqlJs()
    const db = new SQL.Database(dbBytes)

    // Pick a shop that has reviews
    const stmt = db.prepare('SELECT shop_id FROM reviews GROUP BY shop_id HAVING COUNT(*) >= 3 LIMIT 1')
    expect(stmt.step()).toBe(true)
    const { shop_id } = stmt.getAsObject() as { shop_id: string }
    stmt.free()

    const shop = getShopById(db, shop_id)
    expect(shop).not.toBeNull()
    expect(shop!.id).toBe(shop_id)
    expect(shop!.name).toBeTypeOf('string')

    const reviews = getReviewsByShopId(db, shop_id, 50)
    expect(reviews.length).toBeGreaterThanOrEqual(3)
    for (const r of reviews) {
      expect(r.shop_id).toBe(shop_id)
      expect(r.text.length).toBeGreaterThan(0)
    }

    expect(getShopById(db, 'non-existent-id')).toBeNull()
    expect(getReviewsByShopId(db, 'non-existent-id')).toEqual([])

    db.close()
  }, 60000)

  it('runs a near-me query and returns rows within radius, with distance_m attached', async () => {
    const gz = readFileSync(DB_PATH)
    const dbBytes = pako.ungzip(gz)

    const SQL = await initSqlJs()
    const db = new SQL.Database(dbBytes)

    const toranomonHills = { lat: 35.6678, lng: 139.7494 }
    const result = searchShops(db, {
      near: { ...toranomonHills, radiusM: 500 },
      sort: 'distance',
      limit: 10
    })
    expect(result.rows.length).toBeGreaterThan(0)
    expect(result.origin).toEqual(toranomonHills)

    let prev = -1
    for (const r of result.rows) {
      expect(r.distance_m).toBeTypeOf('number')
      expect(r.distance_m!).toBeGreaterThanOrEqual(prev)
      prev = r.distance_m!
      expect(r.distance_m!).toBeLessThanOrEqual(500)
    }

    db.close()
  }, 60000)
})
