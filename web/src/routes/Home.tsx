import { Link } from 'react-router-dom'
import { PRESETS } from '../lib/presets'

export function Home() {
  return (
    <div className="p-4 space-y-6">
      <header>
        <h1 className="text-2xl font-bold">外食メモ</h1>
        <p className="text-sm text-neutral-400">東京23区 / 個人用</p>
      </header>

      <section>
        <Link
          to="/near"
          className="block rounded-xl border border-amber-500/50 bg-gradient-to-br from-amber-500/20 to-amber-700/10 p-5 active:scale-[0.98] transition-transform"
        >
          <div className="text-lg font-bold text-amber-200">いまから行ける</div>
          <div className="text-xs text-amber-100/70 mt-1">現在地周辺 / 営業中</div>
        </Link>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-neutral-400 mb-2">プリセット</h2>
        <div className="space-y-2">
          {Object.entries(PRESETS).map(([key, preset]) => (
            <Link
              key={key}
              to={`/search?preset=${encodeURIComponent(key)}`}
              className="block rounded-xl border border-neutral-800 bg-neutral-900 p-4 active:bg-neutral-800"
            >
              <div className="font-semibold">{key}</div>
              <div className="text-xs text-neutral-400 mt-1">{preset.description}</div>
            </Link>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-neutral-400 mb-2">設定</h2>
        <Link
          to="/settings"
          className="block rounded-xl border border-neutral-800 bg-neutral-900 p-4 active:bg-neutral-800"
        >
          DB状態・訪問記録
        </Link>
      </section>
    </div>
  )
}
