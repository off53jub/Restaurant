import type { Preset } from './types'

export const CORE_TORANOMON = [
  '虎ノ門', '新橋', '赤坂', '銀座', '六本木', '汐留', '霞が関',
  '内幸町', '浜松町', '西新橋', '麻布', '新富', '築地', '愛宕'
]

export const CORE_SHINJUKU = [
  '新宿', '西新宿', '歌舞伎町', '代々木', '千駄ヶ谷', '信濃町',
  '四谷', '四ツ谷', '曙橋', '市ヶ谷', '中野坂上'
]

export const PRESETS: Record<string, Preset> = {
  kaishoku: {
    description: '役員会食（虎ノ門3km / 完全個室 / 5-8名 / 喫煙可 / 7,500-8,800円コース）',
    area_keywords: CORE_TORANOMON,
    require_fully_private: true,
    require_mid_room: true,
    smoking: 'allowed',
    price_min: 7500,
    price_max: 8800,
    scene: 'kaishoku',
    sort: 'composite'
  },
  instagram_shinjuku: {
    description: '新宿3km / インスタ映えデート / 5,000-8,000円 / 半個室OK',
    area_keywords: CORE_SHINJUKU,
    smoking: 'any',
    price_min: 5000,
    price_max: 8000,
    instagram_score_min: 6,
    scene: 'instagram',
    sort: 'composite'
  },
  date_shinjuku: {
    description: '新宿3km / 落ち着いた大人デート / 5,000-8,000円 / 半個室OK',
    area_keywords: CORE_SHINJUKU,
    smoking: 'any',
    price_min: 5000,
    price_max: 8000,
    atmosphere_calm_min: 50,
    atmosphere_special_min: 30,
    scene: 'date',
    sort: 'composite'
  }
}

export function getPresets(): Record<string, Preset> {
  return PRESETS
}
