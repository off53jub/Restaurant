import initSqlJs, { type SqlJsStatic, type Database } from 'sql.js'

let sqlPromise: Promise<SqlJsStatic> | null = null

function loadSqlJs(): Promise<SqlJsStatic> {
  if (!sqlPromise) {
    sqlPromise = initSqlJs({
      locateFile: (file: string) =>
        new URL(`../../node_modules/sql.js/dist/${file}`, import.meta.url).href
    })
  }
  return sqlPromise
}

export async function openDatabase(buf: Uint8Array): Promise<Database> {
  const SQL = await loadSqlJs()
  return new SQL.Database(buf)
}
