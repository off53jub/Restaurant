import { describe, expect, it } from 'vitest'
import { estimateWalkMinutes, formatDistance, haversineMeters } from '../src/lib/geo'

describe('haversineMeters', () => {
  it('returns 0 for same point', () => {
    expect(haversineMeters({ lat: 35.6685, lng: 139.7456 }, { lat: 35.6685, lng: 139.7456 })).toBe(0)
  })

  it('returns ~1.1km between Toranomon and Tameike-Sanno (sanity)', () => {
    const d = haversineMeters({ lat: 35.6685, lng: 139.7456 }, { lat: 35.6736, lng: 139.7416 })
    expect(d).toBeGreaterThan(500)
    expect(d).toBeLessThan(2000)
  })

  it('1 deg of latitude is ~111km', () => {
    const d = haversineMeters({ lat: 35.0, lng: 139.0 }, { lat: 36.0, lng: 139.0 })
    expect(d).toBeGreaterThan(110_000)
    expect(d).toBeLessThan(112_000)
  })
})

describe('formatDistance', () => {
  it('uses meters under 1km', () => {
    expect(formatDistance(0)).toBe('0m')
    expect(formatDistance(450)).toBe('450m')
    expect(formatDistance(999)).toBe('999m')
  })
  it('uses km at and above 1km', () => {
    expect(formatDistance(1000)).toBe('1.0km')
    expect(formatDistance(2345)).toBe('2.3km')
  })
})

describe('estimateWalkMinutes', () => {
  it('uses 80m/min', () => {
    expect(estimateWalkMinutes(80)).toBe(1)
    expect(estimateWalkMinutes(800)).toBe(10)
  })
})
