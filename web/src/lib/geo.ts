export type LatLng = { lat: number; lng: number }

export class GeoError extends Error {
  constructor(public code: 'denied' | 'unavailable' | 'timeout' | 'unsupported', message: string) {
    super(message)
  }
}

export function getCurrentPosition(options?: PositionOptions): Promise<LatLng> {
  return new Promise((resolve, reject) => {
    if (!('geolocation' in navigator)) {
      reject(new GeoError('unsupported', 'Geolocation not supported'))
      return
    }
    navigator.geolocation.getCurrentPosition(
      pos => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      err => {
        const code =
          err.code === err.PERMISSION_DENIED
            ? 'denied'
            : err.code === err.TIMEOUT
              ? 'timeout'
              : 'unavailable'
        reject(new GeoError(code, err.message))
      },
      { enableHighAccuracy: false, maximumAge: 60_000, timeout: 10_000, ...(options ?? {}) }
    )
  })
}

const R = 6371000

export function haversineMeters(a: LatLng, b: LatLng): number {
  const toRad = (d: number) => (d * Math.PI) / 180
  const dLat = toRad(b.lat - a.lat)
  const dLng = toRad(b.lng - a.lng)
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

export function formatDistance(meters: number): string {
  if (meters < 1000) return `${Math.round(meters)}m`
  return `${(meters / 1000).toFixed(1)}km`
}

export function estimateWalkMinutes(meters: number): number {
  return Math.round(meters / 80)
}
