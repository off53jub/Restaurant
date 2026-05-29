"""1次会の近隣で歩いて行ける2次会候補を抽出する。

会食/デートの後、徒歩数分圏のバー/ダイニングバルから落ち着いた店を提案する。
"""
import math


# シーン別: 2次会に向くジャンル既定
DEFAULT_GENRES_BY_SCENE = {
    "kaishoku": ["バー・カクテル", "ダイニングバー・バル"],
    "date":     ["バー・カクテル", "ダイニングバー・バル"],
    "instagram":["バー・カクテル", "ダイニングバー・バル"],
}
DEFAULT_GENRES = ["バー・カクテル", "ダイニングバー・バル"]


def haversine_m(lat1, lng1, lat2, lng2):
    """2点間の距離をメートルで返す（地球を球で近似）。"""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def find_nijikai(conn, lat, lng, scene=None, max_distance_m=600, limit=3,
                 genres=None, exclude_shop_id=None, prefer_calm=True):
    """(lat, lng) から徒歩 max_distance_m 圏の2次会候補を距離・落ち着き順で返す。

    返り値: [(distance_m, sqlite3.Row), ...]
    """
    if not genres:
        genres = DEFAULT_GENRES_BY_SCENE.get(scene, DEFAULT_GENRES)
    if lat is None or lng is None:
        return []
    # 矩形プレフィルタ（経度1度は東京で約91km）
    dlat = max_distance_m / 111000.0
    dlng = max_distance_m / (111000.0 * math.cos(math.radians(lat)))
    placeholders = ",".join("?" * len(genres))
    sql = f"""
    SELECT s.*, j.*
    FROM shops s
    JOIN judgements j ON j.shop_id = s.id
    WHERE s.lat BETWEEN ? AND ?
      AND s.lng BETWEEN ? AND ?
      AND s.genre_name IN ({placeholders})
      AND (j.fetch_error IS NULL OR j.fetch_error = '')
    """
    params = [lat - dlat, lat + dlat, lng - dlng, lng + dlng, *genres]
    if exclude_shop_id:
        sql += " AND s.id != ?"
        params.append(exclude_shop_id)
    rows = list(conn.execute(sql, params))
    out = []
    for r in rows:
        if r["lat"] is None or r["lng"] is None:
            continue
        d = haversine_m(lat, lng, r["lat"], r["lng"])
        if d > max_distance_m:
            continue
        out.append((int(round(d)), r))
    # 落ち着き降順 → 距離昇順
    out.sort(key=lambda x: (
        -(x[1]["atmosphere_calm"] or 0) if prefer_calm else 0,
        x[0],
    ))
    return out[:limit]


def format_nijikai_line(distance_m, r):
    """2次会候補をテキスト出力用の1行に。"""
    calm = r["atmosphere_calm"]
    calm_str = f"落ち着き{calm}" if calm is not None else "落ち着き?"
    return (
        f"     ▸ {r['name'][:32]} ({distance_m}m / {r['genre_name']} / {calm_str})"
        f" — {r['pc_url']}"
    )
