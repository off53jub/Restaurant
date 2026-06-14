const STORAGE_KEY = 'app_token'

function expectedToken(): string {
  return (import.meta.env.VITE_APP_TOKEN as string | undefined) ?? ''
}

export function ensureToken(): { ok: boolean; expected: boolean } {
  const expected = expectedToken()
  if (!expected) {
    // No token configured = no gate (local dev only)
    return { ok: true, expected: false }
  }

  const url = new URL(window.location.href)
  const fromUrl = url.searchParams.get('token') ?? extractHashParam('token')
  if (fromUrl) {
    if (fromUrl === expected) {
      localStorage.setItem(STORAGE_KEY, fromUrl)
      // Strip the token from the URL so it doesn't get bookmarked elsewhere.
      url.searchParams.delete('token')
      window.history.replaceState({}, '', url.toString())
      return { ok: true, expected: true }
    }
    return { ok: false, expected: true }
  }

  const saved = localStorage.getItem(STORAGE_KEY)
  return { ok: saved === expected, expected: true }
}

function extractHashParam(key: string): string | null {
  const hash = window.location.hash.replace(/^#/, '')
  if (!hash) return null
  const params = new URLSearchParams(hash)
  return params.get(key)
}
