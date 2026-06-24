import type { ShopRow, SceneName } from './types'

type WeightMap = Record<string, number>
type Profile = { weights: WeightMap; price_target: [number, number] }

export const SCENE_PROFILES: Record<SceneName, Profile> = {
  kaishoku: {
    weights: {
      calm: 0.22, special: 0.12, price_fit: 0.15,
      private: 0.18, mid_room: 0.08, kaishoku: 0.05,
      kaishoku_actual: 0.20
    },
    price_target: [7500, 8800]
  },
  date: {
    weights: {
      calm: 0.25, special: 0.25, price_fit: 0.13,
      private: 0.08, instagram: 0.14,
      date_actual: 0.15
    },
    price_target: [5000, 8000]
  },
  instagram: {
    weights: {
      instagram: 0.45, special: 0.28, calm: 0.12, price_fit: 0.15
    },
    price_target: [5000, 8000]
  }
}

export function priceFit(prices: number[], lo: number, hi: number): number {
  if (!prices || prices.length === 0) return 0.3
  if (prices.some(p => p >= lo && p <= hi)) return 1.0
  const nearest = prices.reduce((best, p) => {
    const d = Math.min(Math.abs(p - lo), Math.abs(p - hi))
    return d < best.d ? { p, d } : best
  }, { p: prices[0], d: Infinity }).p
  const d = Math.min(Math.abs(nearest - lo), Math.abs(nearest - hi))
  return Math.max(0.0, 1.0 - d / 3000.0)
}

type JudgementLike = Partial<ShopRow> & Record<string, unknown>

function get(j: JudgementLike, key: string): unknown {
  return (j as Record<string, unknown>)[key]
}

function component(name: string, j: JudgementLike, prices: number[], target: [number, number]): number {
  switch (name) {
    case 'calm':
      return (Number(get(j, 'atmosphere_calm') ?? 0)) / 100.0
    case 'special':
      return (Number(get(j, 'atmosphere_special') ?? 0)) / 100.0
    case 'private': {
      const v = get(j, 'fully_private_room')
      if (v === 1 || v === true) return 1.0
      if (v === null || v === undefined) return 0.4
      return 0.0
    }
    case 'mid_room': {
      const v = get(j, 'mid_room_ok')
      return v === 1 || v === true ? 1.0 : 0.0
    }
    case 'instagram':
      return Math.min(Number(get(j, 'instagram_score') ?? 0) / 8.0, 1.0)
    case 'kaishoku':
      return Math.min(Number(get(j, 'kaishoku_score') ?? 0) / 10.0, 1.0)
    case 'kaishoku_actual':
    case 'date_actual': {
      const raw = get(j, 'hotpepper_review_scenes')
      if (!raw || typeof raw !== 'string') return 0.0
      let scenes: Record<string, number>
      try {
        scenes = JSON.parse(raw)
      } catch {
        return 0.0
      }
      const key = name === 'kaishoku_actual' ? 'kaishoku' : 'date'
      return Math.min((scenes[key] ?? 0) / 30.0, 1.0)
    }
    case 'price_fit':
      return priceFit(prices, target[0], target[1])
    default:
      return 0.0
  }
}

export function compositeScore(
  j: JudgementLike,
  prices: number[],
  scene: SceneName,
  priceTarget?: [number, number]
): number {
  const profile = SCENE_PROFILES[scene]
  const target: [number, number] = priceTarget ?? profile.price_target
  const weights = profile.weights
  const total = Object.values(weights).reduce((a, b) => a + b, 0)
  let s = 0
  for (const [name, w] of Object.entries(weights)) {
    s += w * component(name, j, prices, target)
  }
  return Math.round(1000.0 * s / total) / 10
}
