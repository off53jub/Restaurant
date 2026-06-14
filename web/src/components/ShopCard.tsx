import type { ShopRow, SceneName } from '../lib/types'
import { compositeScore } from '../lib/score'

type Props = {
  shop: ShopRow
  scene: SceneName | null
  priceBand: [number, number] | null
  rank: number
}

function bar(v: number | null): string {
  if (v == null) return 'データなし'
  const filled = Math.floor(v / 10)
  return '█'.repeat(filled) + '░'.repeat(10 - filled)
}

function smokingLabel(s: ShopRow['smoking_at_seat']): string {
  switch (s) {
    case 'allowed': return '○ 喫煙可'
    case 'partial': return '△ 分煙'
    case 'forbidden': return '× 全面禁煙'
    default: return '? 記載なし'
  }
}

export function ShopCard({ shop, scene, priceBand, rank }: Props) {
  const prices: number[] = JSON.parse(shop.drink_course_prices_json ?? '[]')
  const igHits: string[] = JSON.parse(shop.instagram_hits_json ?? '[]')
  const fit = scene
    ? compositeScore(shop, prices, scene, priceBand ?? undefined)
    : null
  const bandPrices = priceBand
    ? prices.filter(p => p >= priceBand[0] && p <= priceBand[1])
    : []

  return (
    <article className="rounded-xl border border-neutral-800 bg-neutral-900 p-4 space-y-2">
      <header className="flex items-start justify-between gap-2">
        <div>
          <div className="text-xs text-neutral-500">#{rank}</div>
          <h3 className="text-base font-semibold">{shop.name}</h3>
          <div className="text-xs text-neutral-400">{shop.genre_name}</div>
        </div>
        {fit !== null && (
          <div className="text-right shrink-0">
            <div className="text-2xl font-bold text-amber-400">{fit}</div>
            <div className="text-[10px] text-neutral-500">適合度/100</div>
          </div>
        )}
      </header>

      {shop.catch && (
        <p className="text-xs text-neutral-300 line-clamp-2">{shop.catch}</p>
      )}

      <dl className="grid grid-cols-[5rem_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-neutral-500">住所</dt>
        <dd className="text-neutral-200">{shop.address}</dd>
        {shop.access && (
          <>
            <dt className="text-neutral-500">アクセス</dt>
            <dd className="text-neutral-200 line-clamp-1">{shop.access}</dd>
          </>
        )}
        <dt className="text-neutral-500">落ち着き</dt>
        <dd className="font-mono text-neutral-300">{bar(shop.atmosphere_calm)} {shop.atmosphere_calm ?? '?'}/100</dd>
        <dt className="text-neutral-500">特別感</dt>
        <dd className="font-mono text-neutral-300">{bar(shop.atmosphere_special)} {shop.atmosphere_special ?? '?'}/100</dd>
        {bandPrices.length > 0 && (
          <>
            <dt className="text-neutral-500">★該当帯</dt>
            <dd className="text-amber-300">{bandPrices.map(p => `${p.toLocaleString()}円`).join(' / ')}</dd>
          </>
        )}
        <dt className="text-neutral-500">個室</dt>
        <dd>
          完全{shop.fully_private_room ? '○' : '?'} / 5-8名{shop.mid_room_ok ? '○' : '?'}
        </dd>
        <dt className="text-neutral-500">喫煙</dt>
        <dd>{smokingLabel(shop.smoking_at_seat)}</dd>
        {igHits.length > 0 && (
          <>
            <dt className="text-neutral-500">映え</dt>
            <dd className="text-neutral-300">{igHits.slice(0, 4).join('・')}</dd>
          </>
        )}
      </dl>

      {shop.pc_url && (
        <a
          href={shop.pc_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block text-xs text-sky-400 underline"
        >
          HotPepperで開く →
        </a>
      )}
    </article>
  )
}
