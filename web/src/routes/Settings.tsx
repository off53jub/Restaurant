import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getMeta, listVisits } from '../lib/idbStore'

export function Settings() {
  const [version, setVersion] = useState<string | null>(null)
  const [visitCount, setVisitCount] = useState<number | null>(null)

  useEffect(() => {
    (async () => {
      setVersion(await getMeta<string>('db_version'))
      setVisitCount((await listVisits()).length)
    })()
  }, [])

  return (
    <div className="p-4 space-y-4">
      <header className="flex items-center gap-3">
        <Link to="/" className="text-sky-400 text-sm">← 戻る</Link>
        <h1 className="text-base font-semibold">設定</h1>
      </header>
      <dl className="grid grid-cols-[10rem_1fr] gap-y-2 text-sm">
        <dt className="text-neutral-400">DB version</dt>
        <dd className="font-mono">{version ?? '(none)'}</dd>
        <dt className="text-neutral-400">訪問記録</dt>
        <dd>{visitCount ?? '...'}件</dd>
      </dl>
      <p className="text-xs text-neutral-500">訪問記録のCRUD・Export は Phase C で実装予定。</p>
    </div>
  )
}
