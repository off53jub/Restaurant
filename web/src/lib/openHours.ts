export type OpeningHours = {
  source?: string
  has_lunch?: boolean
  has_dinner?: boolean
  dinner_lo_hour?: number | null
  late_night?: boolean
  dinner_only?: boolean
}

export type OpenStatus =
  | { state: 'open'; until?: number }
  | { state: 'closed' }
  | { state: 'unknown' }

export function isOpenAt(oh: OpeningHours | null | undefined, hour: number): OpenStatus {
  if (!oh) return { state: 'unknown' }
  if (hour >= 11 && hour < 14) {
    return oh.has_lunch ? { state: 'open' } : { state: 'closed' }
  }
  if (hour >= 17 && hour < 23) {
    if (!oh.has_dinner) return { state: 'closed' }
    const lo = oh.dinner_lo_hour
    if (lo != null && lo > hour) return { state: 'open', until: lo }
    if (lo == null) return { state: 'open' }
    return { state: 'closed' }
  }
  if (hour >= 23 || hour < 5) {
    const lo = oh.dinner_lo_hour
    const normalizedHour = hour < 5 ? hour + 24 : hour
    if (oh.late_night) return { state: 'open', until: lo ?? undefined }
    if (lo != null && lo >= normalizedHour) return { state: 'open', until: lo }
    return { state: 'closed' }
  }
  // 14-17 ranged gap (ナカヤスミ) and pre-lunch 5-11
  return { state: 'closed' }
}

export function parseOpeningHours(json: string | null | undefined): OpeningHours | null {
  if (!json) return null
  try {
    return JSON.parse(json) as OpeningHours
  } catch {
    return null
  }
}
