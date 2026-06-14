export type SmokingState = 'allowed' | 'partial' | 'forbidden' | 'unknown' | null

export type SceneName = 'kaishoku' | 'date' | 'instagram'

export type SortMode = 'composite' | 'atmosphere' | 'instagram' | 'score' | 'price' | 'distance'

export type ShopRow = {
  id: string
  name: string
  address: string | null
  station_name: string | null
  lat: number | null
  lng: number | null
  genre_name: string | null
  budget_name: string | null
  access: string | null
  pc_url: string | null
  catch: string | null
  source: string
  photo_url_l: string | null
  photo_url_s: string | null
  // judgement (left/inner joined)
  drink_course_min_yen: number | null
  drink_course_prices_json: string | null
  course_prices_any_json: string | null
  fully_private_room: 0 | 1 | null
  mid_room_ok: 0 | 1 | null
  mid_room_evidence: string | null
  smoking_at_seat: SmokingState
  atmosphere_calm: number | null
  atmosphere_special: number | null
  kaishoku_score: number
  instagram_score: number
  instagram_hits_json: string | null
  shop_description: string | null
  hotpepper_review_count: number | null
  hotpepper_review_scenes: string | null
  opening_hours_json: string | null
  amenities_json: string | null
  // google / social (LEFT JOIN; may be missing)
  google_rating?: number | null
  google_reviews?: number | null
  social_instagram?: string | null
  social_tiktok?: string | null
  social_og_description?: string | null
  social_og_image?: string | null
}

export type Preset = {
  description: string
  area_keywords?: string[]
  require_fully_private?: boolean
  require_mid_room?: boolean
  smoking?: 'allowed' | 'partial_ok' | 'any'
  price_min?: number
  price_max?: number
  atmosphere_calm_min?: number | null
  atmosphere_special_min?: number | null
  instagram_score_min?: number | null
  scene?: SceneName
  sort?: SortMode
}

export type SearchQuery = {
  preset?: string
  areaKeywords?: string[]
  fts?: string
  priceMin?: number
  priceMax?: number
  smoking?: 'any' | 'allowed' | 'partial_ok'
  fullyPrivate?: boolean
  midRoom?: boolean
  calmMin?: number
  specialMin?: number
  igMin?: number
  scene?: SceneName
  sort?: SortMode
  // Phase B
  openNow?: boolean
  near?: { lat: number; lng: number; radiusM: number }
  // visits (resolved in JS, not in SQL — visits live in IndexedDB)
  visited?: boolean
  notVisitedSinceDays?: number
  notWithCompanion?: string
  limit?: number
}

export type Visit = {
  id?: number
  shop_id: string | null
  manual_name?: string | null
  manual_address?: string | null
  manual_url?: string | null
  visited_at: string // YYYY-MM-DD
  rating?: number | null
  cost_per_person?: number | null
  scene?: string | null
  companions?: string | null
  course_name?: string | null
  private_room?: 0 | 1 | null
  would_revisit?: 0 | 1 | null
  notes?: string | null
  tags?: string | null
  created_at: string
  updated_at: string
}
