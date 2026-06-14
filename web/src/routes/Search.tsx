import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useDb } from '../App'
import { PRESETS } from '../lib/presets'
import { searchShops } from '../lib/queryBuilder'
import { ShopCard } from '../components/ShopCard'

const DEFAULT_LIMIT = 30

export function Search() {
  const [params] = useSearchParams()
  const db = useDb()
  const presetKey = params.get('preset') ?? undefined

  const result = useMemo(() => {
    if (!db) return null
    return searchShops(db, {
      preset: presetKey,
      limit: DEFAULT_LIMIT
    })
  }, [db, presetKey])

  if (!db) {
    return <div className="p-4 text-neutral-400">DB読込中…</div>
  }
  if (!result) {
    return <div className="p-4 text-neutral-400">準備中…</div>
  }

  const preset = presetKey ? PRESETS[presetKey] : undefined

  return (
    <div className="p-4 space-y-3">
      <header className="flex items-center gap-3">
        <Link to="/" className="text-sky-400 text-sm">← 戻る</Link>
        <div className="flex-1">
          <h1 className="text-base font-semibold">{presetKey ?? 'アドホック'}</h1>
          {preset && <p className="text-xs text-neutral-400 truncate">{preset.description}</p>}
        </div>
        <div className="text-xs text-neutral-500">{result.rows.length}件</div>
      </header>

      <div className="space-y-3">
        {result.rows.map((shop, i) => (
          <ShopCard
            key={shop.id}
            shop={shop}
            rank={i + 1}
            scene={result.scene}
            priceBand={result.priceBand}
          />
        ))}
      </div>
    </div>
  )
}
