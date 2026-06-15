// 主要駅の座標表。住所LIKEより正確な「駅から半径Nm」検索のために使う。
// 座標は各駅のおおよその中心（小数4桁 ≒ 10m精度、半径検索には十分）。

export type StationGroup = '接待・会食' | 'デート・トレンド' | 'ターミナル・その他'

export type Station = {
  name: string
  lat: number
  lng: number
  group: StationGroup
}

export const STATIONS: Station[] = [
  // 接待・会食
  { name: '虎ノ門', lat: 35.6695, lng: 139.7497, group: '接待・会食' },
  { name: '新橋', lat: 35.6665, lng: 139.7583, group: '接待・会食' },
  { name: '銀座', lat: 35.6717, lng: 139.7650, group: '接待・会食' },
  { name: '赤坂', lat: 35.6726, lng: 139.7363, group: '接待・会食' },
  { name: '六本木', lat: 35.6628, lng: 139.7314, group: '接待・会食' },
  { name: '浜松町', lat: 35.6553, lng: 139.7570, group: '接待・会食' },
  { name: '品川', lat: 35.6285, lng: 139.7387, group: '接待・会食' },
  { name: '東京', lat: 35.6812, lng: 139.7671, group: '接待・会食' },
  { name: '日本橋', lat: 35.6837, lng: 139.7740, group: '接待・会食' },
  { name: '大手町', lat: 35.6864, lng: 139.7665, group: '接待・会食' },
  { name: '神田', lat: 35.6918, lng: 139.7709, group: '接待・会食' },

  // デート・トレンド
  { name: '表参道', lat: 35.6652, lng: 139.7126, group: 'デート・トレンド' },
  { name: '外苑前', lat: 35.6705, lng: 139.7178, group: 'デート・トレンド' },
  { name: '恵比寿', lat: 35.6467, lng: 139.7101, group: 'デート・トレンド' },
  { name: '代官山', lat: 35.6485, lng: 139.7030, group: 'デート・トレンド' },
  { name: '中目黒', lat: 35.6440, lng: 139.6990, group: 'デート・トレンド' },
  { name: '渋谷', lat: 35.6580, lng: 139.7016, group: 'デート・トレンド' },
  { name: '広尾', lat: 35.6516, lng: 139.7220, group: 'デート・トレンド' },
  { name: '麻布十番', lat: 35.6556, lng: 139.7365, group: 'デート・トレンド' },
  { name: '白金高輪', lat: 35.6432, lng: 139.7340, group: 'デート・トレンド' },
  { name: '自由が丘', lat: 35.6076, lng: 139.6690, group: 'デート・トレンド' },
  { name: '二子玉川', lat: 35.6118, lng: 139.6266, group: 'デート・トレンド' },

  // ターミナル・その他
  { name: '新宿', lat: 35.6896, lng: 139.7006, group: 'ターミナル・その他' },
  { name: '池袋', lat: 35.7295, lng: 139.7109, group: 'ターミナル・その他' },
  { name: '上野', lat: 35.7141, lng: 139.7774, group: 'ターミナル・その他' },
  { name: '五反田', lat: 35.6258, lng: 139.7237, group: 'ターミナル・その他' },
  { name: '目黒', lat: 35.6339, lng: 139.7158, group: 'ターミナル・その他' },
  { name: '神楽坂', lat: 35.7024, lng: 139.7404, group: 'ターミナル・その他' },
  { name: '人形町', lat: 35.6863, lng: 139.7826, group: 'ターミナル・その他' },
  { name: '月島', lat: 35.6645, lng: 139.7836, group: 'ターミナル・その他' },
  { name: '門前仲町', lat: 35.6717, lng: 139.7965, group: 'ターミナル・その他' },
  { name: '北千住', lat: 35.7497, lng: 139.8048, group: 'ターミナル・その他' },
  { name: '吉祥寺', lat: 35.7030, lng: 139.5800, group: 'ターミナル・その他' },
  { name: '中野', lat: 35.7057, lng: 139.6657, group: 'ターミナル・その他' }
]

const STATION_BY_NAME = new Map(STATIONS.map(s => [s.name, s]))

export function findStation(name: string): Station | undefined {
  return STATION_BY_NAME.get(name.trim())
}

export const STATION_GROUPS: StationGroup[] = [
  '接待・会食',
  'デート・トレンド',
  'ターミナル・その他'
]
