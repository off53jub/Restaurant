import { describe, expect, it } from 'vitest'
import { compositeScore, priceFit } from '../src/lib/score'

describe('priceFit', () => {
  it('returns 1.0 when any price is inside the band', () => {
    expect(priceFit([6000, 8000], 7500, 8800)).toBe(1.0)
  })

  it('returns 0.3 when no prices known', () => {
    expect(priceFit([], 7500, 8800)).toBe(0.3)
  })

  it('decays linearly to 1500yen distance', () => {
    expect(Math.abs(priceFit([10300], 7500, 8800) - 0.5)).toBeLessThan(1e-9)
  })

  it('hits zero past 3000yen distance', () => {
    expect(priceFit([20000], 7500, 8800)).toBe(0.0)
  })
})

describe('compositeScore - kaishoku', () => {
  it('returns 100 when every component is perfect', () => {
    const j = {
      atmosphere_calm: 100,
      atmosphere_special: 100,
      fully_private_room: 1 as const,
      mid_room_ok: 1 as const,
      instagram_score: 8,
      kaishoku_score: 10,
      hotpepper_review_scenes: '{"kaishoku":30}'
    }
    expect(compositeScore(j as any, [8000], 'kaishoku')).toBe(100.0)
  })

  it('stays small but positive when all components are empty (price unknown adds 0.3)', () => {
    const j = {
      atmosphere_calm: 0,
      atmosphere_special: 0,
      fully_private_room: 0 as const,
      mid_room_ok: 0 as const,
      instagram_score: 0,
      kaishoku_score: 0
    }
    const s = compositeScore(j as any, [], 'kaishoku')
    expect(s).toBeGreaterThan(0)
    expect(s).toBeLessThan(10)
  })

  it('gives partial credit when private flag is unknown vs explicit no', () => {
    const base = {
      atmosphere_calm: 0,
      atmosphere_special: 0,
      mid_room_ok: 0 as const,
      instagram_score: 0,
      kaishoku_score: 0
    }
    const sNone = compositeScore({ ...base, fully_private_room: null } as any, [8000], 'kaishoku')
    const sNo = compositeScore({ ...base, fully_private_room: 0 as const } as any, [8000], 'kaishoku')
    expect(sNone).toBeGreaterThan(sNo)
  })
})

describe('compositeScore - date', () => {
  it('runs on a minimal judgement dict', () => {
    const j = { atmosphere_calm: 80, atmosphere_special: 60 }
    const s = compositeScore(j as any, [6000], 'date')
    expect(s).toBeGreaterThan(0)
    expect(s).toBeLessThanOrEqual(100)
  })

  it('uses date count - not kaishoku count', () => {
    const jKaishokuOnly = {
      atmosphere_calm: 80,
      atmosphere_special: 70,
      fully_private_room: 0 as const,
      instagram_score: 3,
      kaishoku_score: 0,
      hotpepper_review_scenes: '{"kaishoku":50,"date":0}'
    }
    const jDateOnly = { ...jKaishokuOnly, hotpepper_review_scenes: '{"kaishoku":0,"date":50}' }
    const sK = compositeScore(jKaishokuOnly as any, [6000], 'date')
    const sD = compositeScore(jDateOnly as any, [6000], 'date')
    expect(sD).toBeGreaterThan(sK)
  })
})

describe('compositeScore - kaishoku_actual', () => {
  it('lifts the score when review scene count exists, and saturates at 30', () => {
    const base = {
      atmosphere_calm: 70,
      atmosphere_special: 50,
      fully_private_room: 1 as const,
      mid_room_ok: 1 as const,
      instagram_score: 0,
      kaishoku_score: 5,
      hotpepper_review_scenes: null
    }
    const sNo = compositeScore(base as any, [8000], 'kaishoku')
    const s90 = compositeScore({ ...base, hotpepper_review_scenes: '{"kaishoku":90}' } as any, [8000], 'kaishoku')
    const s30 = compositeScore({ ...base, hotpepper_review_scenes: '{"kaishoku":30}' } as any, [8000], 'kaishoku')
    expect(s90).toBeGreaterThan(sNo)
    expect(s90).toBe(s30)
  })

  it('tolerates malformed JSON in hotpepper_review_scenes', () => {
    const j = {
      atmosphere_calm: 50,
      atmosphere_special: 30,
      fully_private_room: 1 as const,
      mid_room_ok: 1 as const,
      instagram_score: 0,
      kaishoku_score: 0,
      hotpepper_review_scenes: 'not-json'
    }
    const s = compositeScore(j as any, [8000], 'kaishoku')
    expect(s).toBeGreaterThan(0)
    expect(s).toBeLessThan(100)
  })
})

describe('compositeScore - price target override', () => {
  it('applies override band instead of profile default', () => {
    const j = {
      atmosphere_calm: 0,
      atmosphere_special: 0,
      fully_private_room: 0 as const,
      mid_room_ok: 0 as const,
      instagram_score: 0,
      kaishoku_score: 0
    }
    const sDefault = compositeScore(j as any, [3000], 'kaishoku')
    const sOverride = compositeScore(j as any, [3000], 'kaishoku', [2500, 3500])
    expect(sOverride).toBeGreaterThan(sDefault)
  })
})
