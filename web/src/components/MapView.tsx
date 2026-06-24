import { useEffect, useRef } from 'react'
import L, { type Map as LMap, type Marker as LMarker, type CircleMarker, type Circle } from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { ShopRowWithDistance } from '../lib/queryBuilder'
import type { LatLng } from '../lib/geo'

type Props = {
  rows: ShopRowWithDistance[]
  origin: LatLng | null
  radiusM?: number
  selectedId?: string | null
  onSelect?: (id: string) => void
  height?: number
}

function colorForRank(rank: number, total: number): string {
  if (total <= 1) return '#fbbf24'
  const t = rank / Math.max(total - 1, 1)
  // amber -> neutral
  if (t < 0.33) return '#fbbf24'
  if (t < 0.66) return '#f97316'
  return '#737373'
}

export function MapView({ rows, origin, radiusM, selectedId, onSelect, height = 280 }: Props) {
  const elRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<LMap | null>(null)
  const markersRef = useRef<Map<string, LMarker | CircleMarker>>(new Map())
  const originMarkerRef = useRef<CircleMarker | null>(null)
  const originCircleRef = useRef<Circle | null>(null)

  useEffect(() => {
    if (!elRef.current || mapRef.current) return
    const center: [number, number] = origin
      ? [origin.lat, origin.lng]
      : rows[0]?.lat != null && rows[0]?.lng != null
        ? [rows[0].lat, rows[0].lng]
        : [35.6685, 139.7456] // Toranomon fallback
    const map = L.map(elRef.current, {
      center,
      zoom: 15,
      zoomControl: true,
      attributionControl: true
    })
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap'
    }).addTo(map)
    mapRef.current = map

    return () => {
      map.remove()
      mapRef.current = null
      markersRef.current.clear()
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    for (const [, m] of markersRef.current) m.remove()
    markersRef.current.clear()

    const bounds: [number, number][] = []
    rows.forEach((r, i) => {
      if (r.lat == null || r.lng == null) return
      const color = colorForRank(i, rows.length)
      const marker = L.circleMarker([r.lat, r.lng], {
        radius: i === 0 ? 9 : 7,
        color: '#111',
        weight: 1,
        fillColor: color,
        fillOpacity: 0.9
      }).addTo(map)
      marker.bindTooltip(`#${i + 1} ${r.name}`, { direction: 'top', offset: [0, -8] })
      marker.on('click', () => onSelect?.(r.id))
      markersRef.current.set(r.id, marker)
      bounds.push([r.lat, r.lng])
    })

    if (origin) {
      originMarkerRef.current?.remove()
      originCircleRef.current?.remove()
      originMarkerRef.current = L.circleMarker([origin.lat, origin.lng], {
        radius: 6,
        color: '#fff',
        weight: 2,
        fillColor: '#0ea5e9',
        fillOpacity: 1
      }).addTo(map)
      if (radiusM) {
        originCircleRef.current = L.circle([origin.lat, origin.lng], {
          radius: radiusM,
          color: '#0ea5e9',
          weight: 1,
          fillOpacity: 0.05
        }).addTo(map)
      }
      bounds.push([origin.lat, origin.lng])
    }

    if (bounds.length > 1) {
      map.fitBounds(bounds, { padding: [24, 24], maxZoom: 16 })
    } else if (bounds.length === 1) {
      map.setView(bounds[0], 16)
    }
  }, [rows, origin, radiusM])

  useEffect(() => {
    if (!selectedId) return
    const m = markersRef.current.get(selectedId)
    const map = mapRef.current
    if (!m || !map) return
    if ('getLatLng' in m) {
      const ll = (m as CircleMarker).getLatLng()
      map.panTo(ll)
      ;(m as CircleMarker).openTooltip()
    }
  }, [selectedId])

  return <div ref={elRef} className="rounded-xl overflow-hidden" style={{ height }} />
}
