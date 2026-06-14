import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useDb } from '../App'
import { getReviewsByShopId, getShopById, type ShopRowWithDistance } from '../lib/queryBuilder'
import { isOpenAt, parseOpeningHours } from '../lib/openHours'

function smokingLabel(s: ShopRowWithDistance['smoking_at_seat']): string {
  switch (s) {
    case 'allowed': return '○ 喫煙可'
    case 'partial': return '△ 分煙'
    case 'forbidden': return '× 全面禁煙'
    default: return '? 記載なし'
  }
}

function mapsHref(shop: ShopRowWithDistance): string | null {
  if (shop.lat != null && shop.lng != null) {
    return `https://www.google.com/maps/search/?api=1&query=${shop.lat},${shop.lng}`
  }
  if (shop.address) return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(shop.address)}`
  return null
}

export function ShopDetail() {
  const { id } = useParams<{ id: string }>()
  const db = useDb()
  const [photoBroken, setPhotoBroken] = useState(false)
  const [showAllReviews, setShowAllReviews] = useState(false)

  const shop = useMemo(() => (db && id ? getShopById(db, id) : null), [db, id])
  const reviews = useMemo(() => (db && id ? getReviewsByShopId(db, id, 100) : []), [db, id])

  useEffect(() => {
    setPhotoBroken(false)
    setShowAllReviews(false)
    window.scrollTo(0, 0)
  }, [id])

  if (!db) return <div className="p-4 text-neutral-400">DB読込中…</div>
  if (!shop) {
    return (
      <div className="p-4 space-y-3">
        <Link to="/" className="text-sky-400 text-sm">← 戻る</Link>
        <div className="text-neutral-400">店舗が見つかりません: {id}</div>
      </div>
    )
  }

  const prices: number[] = JSON.parse(shop.drink_course_prices_json ?? '[]')
  const anyPrices: number[] = JSON.parse(shop.course_prices_any_json ?? '[]')
  const igHits: string[] = JSON.parse(shop.instagram_hits_json ?? '[]')
  const photoSrc = shop.photo_url_l ?? shop.photo_url_s ?? shop.social_og_image ?? null
  const oh = parseOpeningHours(shop.opening_hours_json)
  const openStatus = oh ? isOpenAt(oh, new Date().getHours()) : { state: 'unknown' as const }
  const sceneStats = (() => {
    if (!shop.hotpepper_review_scenes) return null
    try {
      return JSON.parse(shop.hotpepper_review_scenes) as Record<string, number>
    } catch {
      return null
    }
  })()
  const maps = mapsHref(shop)
  const visibleReviews = showAllReviews ? reviews : reviews.slice(0, 10)

  return (
    <div className="pb-8">
      <div className="sticky top-0 z-10 bg-neutral-950/90 backdrop-blur p-3 border-b border-neutral-800">
        <Link to="/" className="text-sky-400 text-sm">← ホーム</Link>
      </div>

      {photoSrc && !photoBroken && (
        <img
          src={photoSrc}
          alt={shop.name}
          loading="eager"
          onError={() => setPhotoBroken(true)}
          className="w-full h-56 object-cover bg-neutral-800"
        />
      )}

      <div className="p-4 space-y-4">
        <header className="space-y-1">
          <div className="text-xs text-neutral-500 flex items-center gap-2 flex-wrap">
            <span>{shop.genre_name}</span>
            {shop.budget_name && <span>· {shop.budget_name}</span>}
            {openStatus.state === 'open' && (
              <span className="text-emerald-400">● 営業中{openStatus.until ? ` (〜${openStatus.until}時)` : ''}</span>
            )}
            {openStatus.state === 'closed' && <span className="text-neutral-500">○ 営業時間外</span>}
          </div>
          <h1 className="text-xl font-bold">{shop.name}</h1>
          {shop.catch && <p className="text-sm text-neutral-300">{shop.catch}</p>}
        </header>

        <section className="flex items-center gap-3 text-sm flex-wrap">
          {shop.pc_url && (
            <a href={shop.pc_url} target="_blank" rel="noopener noreferrer" className="text-sky-400 underline">
              HotPepper
            </a>
          )}
          {maps && (
            <a href={maps} target="_blank" rel="noopener noreferrer" className="text-sky-400 underline">
              地図/経路
            </a>
          )}
          {shop.social_instagram && (
            <a href={shop.social_instagram} target="_blank" rel="noopener noreferrer" className="text-pink-300 underline">
              Instagram
            </a>
          )}
          {shop.social_tiktok && (
            <a href={shop.social_tiktok} target="_blank" rel="noopener noreferrer" className="text-neutral-200 underline">
              TikTok
            </a>
          )}
        </section>

        <section className="space-y-2 text-sm">
          <h2 className="text-xs font-semibold text-neutral-400 uppercase tracking-wide">基本情報</h2>
          <dl className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-1.5">
            <dt className="text-neutral-500">住所</dt>
            <dd>{shop.address}</dd>
            {shop.access && (
              <>
                <dt className="text-neutral-500">アクセス</dt>
                <dd>{shop.access}</dd>
              </>
            )}
            <dt className="text-neutral-500">個室</dt>
            <dd>
              完全個室: {shop.fully_private_room === 1 ? '○' : shop.fully_private_room === 0 ? '×' : '?'} /
              {' '}5-8名対応: {shop.mid_room_ok === 1 ? '○' : '?'}
              {shop.mid_room_evidence && (
                <div className="text-xs text-neutral-500 mt-1">"{shop.mid_room_evidence}"</div>
              )}
            </dd>
            <dt className="text-neutral-500">喫煙</dt>
            <dd>{smokingLabel(shop.smoking_at_seat)}</dd>
            {sceneStats && (
              <>
                <dt className="text-neutral-500">利用シーン</dt>
                <dd className="text-xs">
                  {Object.entries(sceneStats)
                    .filter(([, v]) => v > 0)
                    .map(([k, v]) => `${k}: ${v}件`)
                    .join(' / ') || '記載なし'}
                </dd>
              </>
            )}
          </dl>
        </section>

        <section className="space-y-2 text-sm">
          <h2 className="text-xs font-semibold text-neutral-400 uppercase tracking-wide">雰囲気・適性</h2>
          <dl className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-1.5">
            <dt className="text-neutral-500">落ち着き</dt>
            <dd>{shop.atmosphere_calm ?? '?'} / 100</dd>
            <dt className="text-neutral-500">特別感</dt>
            <dd>{shop.atmosphere_special ?? '?'} / 100</dd>
            <dt className="text-neutral-500">会食適性</dt>
            <dd>{shop.kaishoku_score} / 13</dd>
            <dt className="text-neutral-500">インスタ映え</dt>
            <dd>
              {shop.instagram_score} / 17
              {igHits.length > 0 && (
                <div className="text-xs text-neutral-500 mt-1">{igHits.slice(0, 8).join(' · ')}</div>
              )}
            </dd>
          </dl>
        </section>

        {(prices.length > 0 || anyPrices.length > 0) && (
          <section className="space-y-2 text-sm">
            <h2 className="text-xs font-semibold text-neutral-400 uppercase tracking-wide">コース</h2>
            {prices.length > 0 && (
              <div>
                <div className="text-xs text-neutral-500">飲み放題付き</div>
                <div className="text-amber-300">
                  {prices.map(p => `${p.toLocaleString()}円`).join(' / ')}
                </div>
              </div>
            )}
            {anyPrices.length > 0 && (
              <div>
                <div className="text-xs text-neutral-500">全コース</div>
                <div className="text-neutral-300 text-xs">
                  {anyPrices.map(p => `${p.toLocaleString()}円`).join(' / ')}
                </div>
              </div>
            )}
          </section>
        )}

        {oh && (
          <section className="space-y-2 text-sm">
            <h2 className="text-xs font-semibold text-neutral-400 uppercase tracking-wide">営業</h2>
            <div className="text-xs text-neutral-400">
              ランチ: {oh.has_lunch ? '○' : '×'} / ディナー: {oh.has_dinner ? '○' : '×'}
              {oh.dinner_lo_hour != null && ` (L.O. ${oh.dinner_lo_hour}時)`}
              {oh.late_night && ' / 深夜営業'}
            </div>
          </section>
        )}

        <section className="space-y-2 text-sm">
          <h2 className="text-xs font-semibold text-neutral-400 uppercase tracking-wide">
            口コミ ({reviews.length}件{shop.hotpepper_review_count != null && shop.hotpepper_review_count > reviews.length ? ` / 全${shop.hotpepper_review_count}件中` : ''})
          </h2>
          {reviews.length === 0 ? (
            <div className="text-xs text-neutral-500">口コミなし</div>
          ) : (
            <ul className="space-y-2">
              {visibleReviews.map((r, i) => (
                <li key={i} className="rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-xs leading-relaxed">
                  {r.text}
                </li>
              ))}
            </ul>
          )}
          {!showAllReviews && reviews.length > 10 && (
            <button
              onClick={() => setShowAllReviews(true)}
              className="text-xs text-sky-400 underline"
            >
              全{reviews.length}件を表示
            </button>
          )}
        </section>

        {shop.shop_description && (
          <section className="space-y-2 text-sm">
            <h2 className="text-xs font-semibold text-neutral-400 uppercase tracking-wide">店舗紹介</h2>
            <p className="text-xs text-neutral-300 leading-relaxed whitespace-pre-wrap">
              {shop.shop_description}
            </p>
          </section>
        )}
      </div>
    </div>
  )
}
