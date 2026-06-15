import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useDb } from '../App'
import { getCurrentPosition, GeoError, type LatLng } from '../lib/geo'
import { searchShops } from '../lib/queryBuilder'
import { ShopCard } from '../components/ShopCard'
import { MapView } from '../components/MapView'
import { PRESETS } from '../lib/presets'

type LocState =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'ok'; pos: LatLng }
  | { phase: 'error'; code: GeoError['code']; message: string }

const RADII = [300, 500, 1000, 2000] as const

export function Near() {
  const db = useDb()
  const [loc, setLoc] = useState<LocState>({ phase: 'idle' })
  const [radius, setRadius] = useState<number>(500)
  const [openNow, setOpenNow] = useState<boolean>(true)
  const [preset, setPreset] = useState<string>('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    fetchLocation()
  }, [])

  async function fetchLocation() {
    setLoc({ phase: 'loading' })
    try {
      const pos = await getCurrentPosition()
      setLoc({ phase: 'ok', pos })
    } catch (e) {
      if (e instanceof GeoError) setLoc({ phase: 'error', code: e.code, message: e.message })
      else setLoc({ phase: 'error', code: 'unavailable', message: String(e) })
    }
  }

  const result = useMemo(() => {
    if (!db || loc.phase !== 'ok') return null
    return searchShops(db, {
      preset: preset || undefined,
      near: { lat: loc.pos.lat, lng: loc.pos.lng, radiusM: radius },
      openNow,
      sort: preset ? undefined : 'distance',
      limit: 30
    })
  }, [db, loc, radius, openNow, preset])

  if (!db) return <div className="p-4 text-neutral-400">DB読込中…</div>

  return (
    <div className="p-4 space-y-3">
      <header className="flex items-center gap-3">
        <Link to="/" className="text-sky-400 text-sm">← 戻る</Link>
        <h1 className="text-base font-semibold">いまから行ける</h1>
      </header>

      <div className="rounded-xl border border-neutral-800 bg-neutral-900 p-3 space-y-2">
        <div className="flex items-center gap-2 flex-wrap text-xs">
          <button
            onClick={fetchLocation}
            className="px-3 py-1.5 rounded-md bg-sky-600 active:bg-sky-700 text-white"
          >
            現在地を取得
          </button>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={openNow}
              onChange={e => setOpenNow(e.target.checked)}
              className="accent-amber-500"
            />
            営業中
          </label>
          <div className="flex items-center gap-1">
            {RADII.map(r => (
              <button
                key={r}
                onClick={() => setRadius(r)}
                className={
                  'px-2 py-1 rounded text-[11px] border ' +
                  (r === radius
                    ? 'border-amber-500 bg-amber-500/20 text-amber-300'
                    : 'border-neutral-700 text-neutral-400')
                }
              >
                {r < 1000 ? `${r}m` : `${r / 1000}km`}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-neutral-500">プリセット併用:</span>
          <select
            value={preset}
            onChange={e => setPreset(e.target.value)}
            className="bg-neutral-800 text-neutral-100 rounded px-2 py-1 text-xs border border-neutral-700"
          >
            <option value="">指定なし（距離順）</option>
            {Object.keys(PRESETS).map(k => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
        </div>

        {loc.phase === 'loading' && <div className="text-xs text-neutral-400">位置情報を取得中…</div>}
        {loc.phase === 'error' && (
          <div className="text-xs text-red-400">
            位置情報エラー: {loc.code === 'denied' ? '権限が拒否されました' : loc.message}
          </div>
        )}
        {loc.phase === 'ok' && (
          <div className="text-[11px] text-neutral-500 font-mono">
            {loc.pos.lat.toFixed(5)}, {loc.pos.lng.toFixed(5)}
          </div>
        )}
      </div>

      {result && loc.phase === 'ok' && (
        <>
          <MapView
            rows={result.rows}
            origin={loc.pos}
            radiusM={radius}
            selectedId={selectedId}
            onSelect={setSelectedId}
            height={260}
          />
          <div className="text-xs text-neutral-500">{result.rows.length}件</div>
          <div className="space-y-3">
            {result.rows.map((shop, i) => (
              <div
                key={shop.id}
                onClick={() => setSelectedId(shop.id)}
                className={selectedId === shop.id ? 'ring-2 ring-amber-500 rounded-xl' : ''}
              >
                <ShopCard
                  shop={shop}
                  rank={i + 1}
                  scene={result.scene}
                  priceBand={result.priceBand}
                  priceField={result.priceField}
                />
              </div>
            ))}
            {result.rows.length === 0 && (
              <div className="text-sm text-neutral-500 p-4 text-center">
                条件に合う店が見つかりませんでした。半径を広げるか、営業中フィルタを外してみてください。
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
