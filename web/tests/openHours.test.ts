import { describe, expect, it } from 'vitest'
import { isOpenAt, parseOpeningHours } from '../src/lib/openHours'

describe('isOpenAt', () => {
  it('returns unknown for null', () => {
    expect(isOpenAt(null, 19).state).toBe('unknown')
  })

  it('lunch hour requires has_lunch', () => {
    expect(isOpenAt({ has_lunch: true }, 12).state).toBe('open')
    expect(isOpenAt({ has_lunch: false }, 12).state).toBe('closed')
  })

  it('dinner hour requires has_dinner and dinner_lo_hour > now', () => {
    expect(isOpenAt({ has_dinner: true, dinner_lo_hour: 22 }, 20).state).toBe('open')
    expect(isOpenAt({ has_dinner: true, dinner_lo_hour: 19 }, 20).state).toBe('closed')
    expect(isOpenAt({ has_dinner: true, dinner_lo_hour: null }, 20).state).toBe('open')
    expect(isOpenAt({ has_dinner: false }, 20).state).toBe('closed')
  })

  it('emits the until field when lo hour is known', () => {
    const s = isOpenAt({ has_dinner: true, dinner_lo_hour: 22 }, 20)
    expect(s).toMatchObject({ state: 'open', until: 22 })
  })

  it('late-night hours use late_night or late dinner_lo_hour', () => {
    expect(isOpenAt({ late_night: true, dinner_lo_hour: 25 }, 24).state).toBe('open')
    expect(isOpenAt({ late_night: false, dinner_lo_hour: 25 }, 24).state).toBe('open')
    expect(isOpenAt({ late_night: false, dinner_lo_hour: 22 }, 24).state).toBe('closed')
  })

  it('afternoon gap (14-17) treats as closed', () => {
    expect(isOpenAt({ has_lunch: true, has_dinner: true, dinner_lo_hour: 22 }, 15).state).toBe('closed')
  })
})

describe('parseOpeningHours', () => {
  it('returns null for null / empty / malformed', () => {
    expect(parseOpeningHours(null)).toBeNull()
    expect(parseOpeningHours('')).toBeNull()
    expect(parseOpeningHours('not-json')).toBeNull()
  })
  it('parses valid JSON', () => {
    expect(parseOpeningHours('{"has_lunch":true}')).toEqual({ has_lunch: true })
  })
})
