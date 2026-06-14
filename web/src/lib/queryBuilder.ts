import type { Database, BindParams } from 'sql.js'
import type { ShopRow, SearchQuery, SceneName } from './types'
import { PRESETS } from './presets'
import { compositeScore } from './score'

type WhereBuild = {
  where: string[]
  args: (string | number)[]
  hasPrice: boolean
  priceBand: [number, number] | null
  fts: string | null
}

function buildWhere(q: SearchQuery): WhereBuild {
  const preset = q.preset ? PRESETS[q.preset] : undefined
  const where: string[] = []
  const args: (string | number)[] = []

  const keywords = q.areaKeywords ?? preset?.area_keywords
  if (keywords && keywords.length) {
    const ors = keywords.map(() => 's.address LIKE ?').join(' OR ')
    where.push(`(${ors})`)
    for (const k of keywords) args.push(`%${k}%`)
  }

  const pmin = q.priceMin ?? preset?.price_min ?? null
  const pmax = q.priceMax ?? preset?.price_max ?? null
  const hasPrice = pmin !== null && pmax !== null

  if (q.fullyPrivate ?? preset?.require_fully_private) where.push('j.fully_private_room = 1')
  if (q.midRoom ?? preset?.require_mid_room) where.push('j.mid_room_ok = 1')

  const smk = q.smoking ?? preset?.smoking ?? 'any'
  if (smk === 'allowed') where.push("j.smoking_at_seat = 'allowed'")
  else if (smk === 'partial_ok') where.push("j.smoking_at_seat IN ('allowed','partial')")

  const calmMin = q.calmMin ?? preset?.atmosphere_calm_min ?? null
  if (calmMin !== null && calmMin !== undefined) {
    where.push('COALESCE(j.atmosphere_calm,0) >= ?')
    args.push(calmMin)
  }
  const specialMin = q.specialMin ?? preset?.atmosphere_special_min ?? null
  if (specialMin !== null && specialMin !== undefined) {
    where.push('COALESCE(j.atmosphere_special,0) >= ?')
    args.push(specialMin)
  }
  const igMin = q.igMin ?? preset?.instagram_score_min ?? null
  if (igMin !== null && igMin !== undefined) {
    where.push('COALESCE(j.instagram_score,0) >= ?')
    args.push(igMin)
  }

  // Phase B: near box prefilter
  if (q.near) {
    const dlat = q.near.radiusM / 111000
    const dlng = q.near.radiusM / (111000 * Math.cos(q.near.lat * Math.PI / 180))
    where.push('s.lat BETWEEN ? AND ? AND s.lng BETWEEN ? AND ?')
    args.push(q.near.lat - dlat, q.near.lat + dlat, q.near.lng - dlng, q.near.lng + dlng)
  }

  // Phase B: openNow (rough hour-based using opening_hours_json)
  if (q.openNow) {
    const hour = new Date().getHours()
    if (hour >= 11 && hour < 14) {
      where.push("json_extract(j.opening_hours_json,'$.has_lunch') = 1")
    } else if (hour >= 17 && hour < 23) {
      where.push(
        "json_extract(j.opening_hours_json,'$.has_dinner') = 1 AND (" +
        "json_extract(j.opening_hours_json,'$.dinner_lo_hour') IS NULL " +
        'OR json_extract(j.opening_hours_json,\'$.dinner_lo_hour\') > ?)'
      )
      args.push(hour)
    } else if (hour >= 23 || hour < 5) {
      where.push(
        "(json_extract(j.opening_hours_json,'$.late_night') = 1 " +
        "OR json_extract(j.opening_hours_json,'$.dinner_lo_hour') >= 23)"
      )
    }
  }

  where.push("(j.fetch_error IS NULL OR j.fetch_error = '')")

  return {
    where,
    args,
    hasPrice,
    priceBand: hasPrice ? [pmin!, pmax!] : null,
    fts: q.fts ?? null
  }
}

function haversineM(aLat: number, aLng: number, bLat: number, bLng: number): number {
  const R = 6371000
  const toRad = (d: number) => (d * Math.PI) / 180
  const dLat = toRad(bLat - aLat)
  const dLng = toRad(bLng - aLng)
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) * Math.sin(dLng / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

export type SearchResult = {
  rows: ShopRow[]
  priceBand: [number, number] | null
  scene: SceneName | null
}

export function searchShops(db: Database, q: SearchQuery): SearchResult {
  const built = buildWhere(q)
  const preset = q.preset ? PRESETS[q.preset] : undefined
  const scene: SceneName | null = q.scene ?? (preset?.scene as SceneName | undefined) ?? null
  const sortMode = q.sort ?? preset?.sort ?? (scene ? 'composite' : 'atmosphere')

  let whereSql = built.where.join(' AND ') || '1=1'
  let ftsJoin = ''
  const args: (string | number)[] = [...built.args]
  if (built.fts) {
    ftsJoin = ' JOIN shops_fts f ON f.rowid = s.rowid'
    whereSql = 'shops_fts MATCH ? AND ' + whereSql
    args.unshift(built.fts)
  }

  let priceJoin = ''
  if (built.hasPrice && built.priceBand) {
    const [pmin, pmax] = built.priceBand
    priceJoin =
      ' AND EXISTS (SELECT 1 FROM json_each(j.drink_course_prices_json) je ' +
      `WHERE CAST(je.value AS INTEGER) BETWEEN ${pmin} AND ${pmax})`
  }

  const sql = `
    SELECT s.id, s.name, s.address, s.station_name, s.lat, s.lng,
           s.genre_name, s.budget_name, s.access, s.pc_url, s.catch, s.source,
           j.drink_course_min_yen, j.drink_course_prices_json, j.course_prices_any_json,
           j.fully_private_room, j.mid_room_ok, j.mid_room_evidence,
           j.smoking_at_seat, j.atmosphere_calm, j.atmosphere_special,
           j.kaishoku_score, j.instagram_score, j.instagram_hits_json,
           j.shop_description, j.hotpepper_review_count, j.hotpepper_review_scenes,
           j.opening_hours_json, j.amenities_json,
           g.rating AS google_rating, g.user_ratings_total AS google_reviews,
           so.instagram_url AS social_instagram, so.tiktok_url AS social_tiktok,
           so.og_description AS social_og_description
    FROM shops s
    ${ftsJoin}
    JOIN judgements j ON j.shop_id = s.id
    LEFT JOIN google g ON g.shop_id = s.id
    LEFT JOIN social so ON so.shop_id = s.id
    WHERE ${whereSql} ${priceJoin}
  `

  const stmt = db.prepare(sql)
  stmt.bind(args as BindParams)
  const rows: ShopRow[] = []
  while (stmt.step()) {
    rows.push(stmt.getAsObject() as unknown as ShopRow)
  }
  stmt.free()

  // sort in JS
  if (sortMode === 'composite' && scene) {
    const band = built.priceBand ?? undefined
    rows.sort((a, b) => {
      const pa = JSON.parse(a.drink_course_prices_json || '[]') as number[]
      const pb = JSON.parse(b.drink_course_prices_json || '[]') as number[]
      return compositeScore(b, pb, scene, band) - compositeScore(a, pa, scene, band)
    })
  } else if (sortMode === 'distance' && q.near) {
    const { lat, lng } = q.near
    rows.sort((a, b) => {
      const da = a.lat != null && a.lng != null ? haversineM(lat, lng, a.lat, a.lng) : Infinity
      const db = b.lat != null && b.lng != null ? haversineM(lat, lng, b.lat, b.lng) : Infinity
      return da - db
    })
  } else if (sortMode === 'atmosphere') {
    rows.sort((a, b) =>
      (b.atmosphere_calm ?? 0) - (a.atmosphere_calm ?? 0) ||
      (b.atmosphere_special ?? 0) - (a.atmosphere_special ?? 0) ||
      b.kaishoku_score - a.kaishoku_score
    )
  } else if (sortMode === 'instagram') {
    rows.sort((a, b) =>
      b.instagram_score - a.instagram_score ||
      (b.atmosphere_special ?? 0) - (a.atmosphere_special ?? 0)
    )
  } else if (sortMode === 'score') {
    rows.sort((a, b) =>
      b.kaishoku_score - a.kaishoku_score ||
      (a.drink_course_min_yen ?? Infinity) - (b.drink_course_min_yen ?? Infinity)
    )
  } else if (sortMode === 'price') {
    rows.sort((a, b) => (a.drink_course_min_yen ?? Infinity) - (b.drink_course_min_yen ?? Infinity))
  }

  const limit = q.limit && q.limit > 0 ? q.limit : rows.length
  return { rows: rows.slice(0, limit), priceBand: built.priceBand, scene }
}

export function distanceM(aLat: number, aLng: number, bLat: number, bLng: number): number {
  return haversineM(aLat, aLng, bLat, bLng)
}
