import { createContext, useContext, useEffect, useState } from 'react'
import { BrowserRouter, HashRouter, Route, Routes } from 'react-router-dom'
import type { Database } from 'sql.js'
import { ensureToken } from './lib/auth'
import { loadDb, type LoadProgress } from './lib/dbLoader'
import { DB_SOURCE } from './lib/config'
import { Home } from './routes/Home'
import { Search } from './routes/Search'
import { Settings } from './routes/Settings'
import { Near } from './routes/Near'

const DbContext = createContext<Database | null>(null)
export function useDb(): Database | null {
  return useContext(DbContext)
}

// HashRouter for GitHub Pages compatibility (no 404 fallback needed).
const Router = import.meta.env.PROD ? HashRouter : BrowserRouter

function ProgressView({ progress }: { progress: LoadProgress | null }) {
  if (!progress) return <div className="text-neutral-400">起動中…</div>
  switch (progress.phase) {
    case 'cache-hit':
      return <div className="text-neutral-400">キャッシュから復元中…</div>
    case 'download': {
      const total = progress.total
      const pct = total ? Math.round((progress.received / total) * 100) : null
      const sizeMb = (progress.received / 1024 / 1024).toFixed(1)
      const totalMb = total ? (total / 1024 / 1024).toFixed(0) : '?'
      return <div className="text-neutral-400">DB取得中… {sizeMb} / {totalMb} MB {pct !== null && `(${pct}%)`}</div>
    }
    case 'decompress':
      return <div className="text-neutral-400">展開中…</div>
    case 'persist':
      return <div className="text-neutral-400">保存中…</div>
    case 'open':
      return <div className="text-neutral-400">DB初期化中…</div>
    case 'ready':
      return <div className="text-neutral-400">完了</div>
    case 'error':
      return <div className="text-red-400">エラー: {progress.error.message}</div>
  }
}

export default function App() {
  const [authState] = useState(() => ensureToken())
  const [db, setDb] = useState<Database | null>(null)
  const [progress, setProgress] = useState<LoadProgress | null>(null)

  useEffect(() => {
    if (!authState.ok) return
    let cancelled = false
    loadDb(DB_SOURCE, p => {
      if (!cancelled) setProgress(p)
    })
      .then(d => {
        if (!cancelled) setDb(d)
      })
      .catch(() => {/* surfaced via progress */})
    return () => {
      cancelled = true
    }
  }, [authState.ok])

  if (!authState.ok) {
    return (
      <div className="h-full flex items-center justify-center p-6">
        <div className="text-center">
          <div className="text-2xl font-bold mb-2">Unauthorized</div>
          <p className="text-sm text-neutral-500">
            ?token=... 付きのURLからアクセスしてください
          </p>
        </div>
      </div>
    )
  }

  if (!db) {
    return (
      <div className="h-full flex items-center justify-center p-6">
        <div className="text-center space-y-2">
          <div className="text-xl font-semibold">外食メモ</div>
          <ProgressView progress={progress} />
        </div>
      </div>
    )
  }

  return (
    <DbContext.Provider value={db}>
      <Router>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/search" element={<Search />} />
          <Route path="/near" element={<Near />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </Router>
    </DbContext.Provider>
  )
}
