import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useDb } from '../App'
import { PRESETS } from '../lib/presets'
import { findStation } from '../lib/stations'
import { searchShops } from '../lib/queryBuilder'
import type { SceneName, SortMode, SearchQuery } from '../lib/types'
import { ShopCard } from '../components/ShopCard'

const DEFAULT_LIMIT = 40

const SCENE_LABEL: Record<SceneName, string> = {
  kaishoku: '接待・会食',
  date: '大人デート',
  instagram: '映えデート'
}

function buildQuery(params: URLSearchParams): { query: SearchQuery; title: string; subtitle: string } {
  const presetKey = params.get('preset') ?? undefined
  if (presetKey && PRESETS[presetKey]) {
    return {
      query: { preset: presetKey, limit: DEFAULT_LIMIT },
      title: presetKey,
      subtitle: PRESETS[presetKey].description
    }
  }

  const scene = (params.get('scene') as SceneName | null) ?? undefined
  const pf = (params.get('pf') as 'drink' | 'any' | null) ?? undefined
  const sort = (params.get('sort') as SortMode | null) ?? undefined
  const pmin = params.get('pmin')
  const pmax = params.get('pmax')
  const fp = params.get('fp') === '1'
  const smk = params.get('smk') as 'allowed' | 'partial_ok' | null
  const stationName = params.get('station')
  const area = params.get('area')
  const radius = Number(params.get('radius') ?? '1200')

  const query: SearchQuery = {
    scene,
    priceField: pf,
    sort,
    limit: DEFAULT_LIMIT
  }
  if (pmin && pmax) {
    query.priceMin = Number(pmin)
    query.priceMax = Number(pmax)
  }
  if (fp) query.fullyPrivate = true
  if (smk) query.smoking = smk

  const subParts: string[] = []
  let title = scene ? SCENE_LABEL[scene] : '検索結果'

  const station = stationName ? findStation(stationName) : undefined
  if (station) {
    query.near = { lat: station.lat, lng: station.lng, radiusM: radius }
    title = `${station.name}駅`
    subParts.push(`半径${radius < 1000 ? `${radius}m` : `${radius / 1000}km`}`)
  } else if (stationName) {
    // 座標未登録の駅名 → 住所LIKEにフォールバック
    query.areaKeywords = [stationName]
    title = stationName
  } else if (area) {
    query.areaKeywords = [area]
    title = area
  }

  if (scene) subParts.push(SCENE_LABEL[scene])
  if (pmin && pmax) {
    subParts.push(`${Number(pmin).toLocaleString()}〜${Number(pmax).toLocaleString()}円`)
  }
  if (fp) subParts.push('完全個室')
  if (smk === 'allowed') subParts.push('喫煙可')

  return { query, title, subtitle: subParts.join(' / ') }
}

export function Search() {
  const [params] = useSearchParams()
  const db = useDb()

  const { query, title, subtitle } = useMemo(() => buildQuery(params), [params])

  const result = useMemo(() => {
    if (!db) return null
    return searchShops(db, query)
  }, [db, query])

  if (!db) {
    return <div className="p-4 text-neutral-400">DB読込中…</div>
  }
  if (!result) {
    return <div className="p-4 text-neutral-400">準備中…</div>
  }

  return (
    <div className="p-4 space-y-3">
      <header className="flex items-center gap-3">
        <Link to="/" className="text-sky-400 text-sm shrink-0">← 戻る</Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-base font-semibold truncate">{title}</h1>
          {subtitle && <p className="text-xs text-neutral-400 truncate">{subtitle}</p>}
        </div>
        <div className="text-xs text-neutral-500 shrink-0">{result.rows.length}件</div>
      </header>

      {result.rows.length === 0 ? (
        <div className="text-sm text-neutral-500 p-6 text-center space-y-1">
          <div>条件に合う店が見つかりませんでした。</div>
          <div className="text-xs">予算を「指定なし」にするか、半径を広げてみてください。</div>
        </div>
      ) : (
        <div className="space-y-3">
          {result.rows.map((shop, i) => (
            <ShopCard
              key={shop.id}
              shop={shop}
              rank={i + 1}
              scene={result.scene}
              priceBand={result.priceBand}
              priceField={result.priceField}
            />
          ))}
        </div>
      )}
    </div>
  )
}
