import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { STATION_GROUPS, STATIONS } from '../lib/stations'

type Purpose = 'settai' | 'date'

const BUDGETS = [
  { label: '指定なし', min: null, max: null },
  { label: '〜5,000円', min: 0, max: 5000 },
  { label: '5,000〜8,000円', min: 5000, max: 8000 },
  { label: '8,000〜12,000円', min: 8000, max: 12000 },
  { label: '12,000〜20,000円', min: 12000, max: 20000 }
] as const

const RADII = [800, 1200, 2000] as const

function Chip({
  active,
  onClick,
  children
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        'px-3 py-1.5 rounded-full text-xs border transition-colors ' +
        (active
          ? 'border-amber-500 bg-amber-500/20 text-amber-200'
          : 'border-neutral-700 text-neutral-300 active:bg-neutral-800')
      }
    >
      {children}
    </button>
  )
}

export function Home() {
  const navigate = useNavigate()
  const [purpose, setPurpose] = useState<Purpose>('settai')
  const [dateInsta, setDateInsta] = useState(false)
  const [station, setStation] = useState<string>('')
  const [areaText, setAreaText] = useState<string>('')
  const [budgetIdx, setBudgetIdx] = useState<number>(3) // 8,000〜12,000
  const [radius, setRadius] = useState<number>(1200)
  const [privateOnly, setPrivateOnly] = useState<boolean>(false)
  const [smokingOk, setSmokingOk] = useState<boolean>(false)

  const canSearch = station !== '' || areaText.trim() !== ''

  function onPickPurpose(p: Purpose) {
    setPurpose(p)
    // 目的に応じた予算デフォルト（ユーザーが指定なしにしていない限り上書き）
    setBudgetIdx(prev => (prev === 0 ? 0 : p === 'settai' ? 3 : 2))
  }

  function runSearch() {
    if (!canSearch) return
    const scene = purpose === 'settai' ? 'kaishoku' : dateInsta ? 'instagram' : 'date'
    const pf = purpose === 'settai' ? 'drink' : 'any'
    const params = new URLSearchParams()
    params.set('scene', scene)
    params.set('pf', pf)
    params.set('sort', 'composite')

    if (station) {
      params.set('station', station)
      params.set('radius', String(radius))
    } else if (areaText.trim()) {
      params.set('area', areaText.trim())
    }

    const b = BUDGETS[budgetIdx]
    if (b.min !== null && b.max !== null) {
      params.set('pmin', String(b.min))
      params.set('pmax', String(b.max))
    }
    if (purpose === 'settai' && privateOnly) params.set('fp', '1')
    if (purpose === 'settai' && smokingOk) params.set('smk', 'allowed')

    navigate(`/search?${params.toString()}`)
  }

  const groupedStations = useMemo(
    () => STATION_GROUPS.map(g => ({ group: g, items: STATIONS.filter(s => s.group === g) })),
    []
  )

  return (
    <div className="p-4 space-y-6">
      <header>
        <h1 className="text-2xl font-bold">外食メモ</h1>
        <p className="text-sm text-neutral-400">東京23区 / 個人用</p>
      </header>

      <section>
        <Link
          to="/near"
          className="block rounded-xl border border-amber-500/50 bg-gradient-to-br from-amber-500/20 to-amber-700/10 p-4 active:scale-[0.98] transition-transform"
        >
          <div className="text-base font-bold text-amber-200">📍 いまから行ける</div>
          <div className="text-xs text-amber-100/70 mt-0.5">現在地周辺 / 営業中</div>
        </Link>
      </section>

      {/* 条件検索フォーム */}
      <section className="space-y-4 rounded-xl border border-neutral-800 bg-neutral-900 p-4">
        {/* 目的 */}
        <div className="space-y-1.5">
          <div className="text-xs font-semibold text-neutral-400">目的</div>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => onPickPurpose('settai')}
              className={
                'rounded-lg py-3 text-sm font-semibold border transition-colors ' +
                (purpose === 'settai'
                  ? 'border-sky-500 bg-sky-500/20 text-sky-200'
                  : 'border-neutral-700 text-neutral-300 active:bg-neutral-800')
              }
            >
              🤝 接待・会食
            </button>
            <button
              type="button"
              onClick={() => onPickPurpose('date')}
              className={
                'rounded-lg py-3 text-sm font-semibold border transition-colors ' +
                (purpose === 'date'
                  ? 'border-pink-500 bg-pink-500/20 text-pink-200'
                  : 'border-neutral-700 text-neutral-300 active:bg-neutral-800')
              }
            >
              💗 デート
            </button>
          </div>
          {purpose === 'date' && (
            <label className="flex items-center gap-2 text-xs text-neutral-300 pt-1">
              <input
                type="checkbox"
                checked={dateInsta}
                onChange={e => setDateInsta(e.target.checked)}
                className="accent-pink-500"
              />
              映え重視（インスタ映えを優先）
            </label>
          )}
          {purpose === 'settai' && (
            <div className="flex items-center gap-4 pt-1">
              <label className="flex items-center gap-2 text-xs text-neutral-300">
                <input
                  type="checkbox"
                  checked={privateOnly}
                  onChange={e => setPrivateOnly(e.target.checked)}
                  className="accent-sky-500"
                />
                完全個室のみ
              </label>
              <label className="flex items-center gap-2 text-xs text-neutral-300">
                <input
                  type="checkbox"
                  checked={smokingOk}
                  onChange={e => setSmokingOk(e.target.checked)}
                  className="accent-sky-500"
                />
                喫煙可
              </label>
            </div>
          )}
        </div>

        {/* 予算 */}
        <div className="space-y-1.5">
          <div className="text-xs font-semibold text-neutral-400">
            予算{purpose === 'settai' ? '（飲み放題コース）' : '（コース料金）'}
          </div>
          <div className="flex flex-wrap gap-2">
            {BUDGETS.map((b, i) => (
              <Chip key={b.label} active={i === budgetIdx} onClick={() => setBudgetIdx(i)}>
                {b.label}
              </Chip>
            ))}
          </div>
        </div>

        {/* 駅 */}
        <div className="space-y-2">
          <div className="text-xs font-semibold text-neutral-400">
            駅・エリア{station && <span className="text-amber-300 ml-2">選択中: {station}</span>}
          </div>
          {groupedStations.map(({ group, items }) => (
            <div key={group} className="space-y-1.5">
              <div className="text-[11px] text-neutral-500">{group}</div>
              <div className="flex flex-wrap gap-1.5">
                {items.map(s => (
                  <Chip
                    key={s.name}
                    active={station === s.name}
                    onClick={() => {
                      setStation(prev => (prev === s.name ? '' : s.name))
                      setAreaText('')
                    }}
                  >
                    {s.name}
                  </Chip>
                ))}
              </div>
            </div>
          ))}
          <input
            type="text"
            value={areaText}
            onChange={e => {
              setAreaText(e.target.value)
              if (e.target.value) setStation('')
            }}
            placeholder="その他の駅・エリア名で検索（例: 神保町）"
            className="w-full mt-1 bg-neutral-800 text-neutral-100 rounded-lg px-3 py-2 text-sm border border-neutral-700 placeholder:text-neutral-600"
          />
          {station && (
            <div className="flex items-center gap-2 pt-1">
              <span className="text-[11px] text-neutral-500">半径</span>
              {RADII.map(r => (
                <Chip key={r} active={r === radius} onClick={() => setRadius(r)}>
                  {r < 1000 ? `${r}m` : `${r / 1000}km`}
                </Chip>
              ))}
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={runSearch}
          disabled={!canSearch}
          className={
            'w-full rounded-lg py-3 text-sm font-bold transition-colors ' +
            (canSearch
              ? 'bg-amber-500 text-neutral-950 active:bg-amber-600'
              : 'bg-neutral-800 text-neutral-600')
          }
        >
          {canSearch ? 'この条件で探す' : '駅・エリアを選んでください'}
        </button>
      </section>

      <section>
        <Link
          to="/settings"
          className="block rounded-xl border border-neutral-800 bg-neutral-900 p-4 active:bg-neutral-800 text-sm"
        >
          DB状態・訪問記録
        </Link>
      </section>
    </div>
  )
}
