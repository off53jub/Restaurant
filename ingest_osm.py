#!/usr/bin/env python3
"""OpenStreetMap (Overpass API) から飲食店を取得して SQLite に UPSERT する。

無料・APIキー不要。OSMはコミュニティ編集なのでカバレッジに偏りはあるが、
HotPepper未掲載の個人店・老舗・カウンター店も拾える。

使い方:
  python ingest_osm.py                # 23区全中心
  python ingest_osm.py --max-centers 2  # 試走
"""
import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests

import db as dbmod

# Overpass APIエンドポイント候補（混雑時切替）
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

ID_PREFIX = "osm:"

# Overpass はマナーとして User-Agent が事実上必須（無記名や curl 系UAは弾かれる）。
# 長すぎる UA も Apache レベルで 406 を返すサーバーがあるので短めに。
UA = "restaurant-filter/0.1"

# 取得対象 amenity と日本語ジャンル名のマッピング
AMENITY_GENRE = {
    "restaurant": "レストラン",
    "cafe": "カフェ・スイーツ",
    "bar": "バー・カクテル",
    "pub": "居酒屋",
    "fast_food": "ファストフード",
    "food_court": "フードコート",
    "ice_cream": "カフェ・スイーツ",
}
# OSM cuisine タグから細分化
CUISINE_GENRE = {
    "japanese": "和食", "sushi": "和食", "ramen": "ラーメン",
    "italian": "イタリアン・フレンチ", "french": "イタリアン・フレンチ",
    "chinese": "中華", "korean": "韓国料理",
    "thai": "アジア・エスニック料理", "vietnamese": "アジア・エスニック料理",
    "indian": "アジア・エスニック料理",
    "yakiniku": "焼肉・ホルモン", "barbecue": "焼肉・ホルモン",
    "izakaya": "居酒屋",
    "cafe": "カフェ・スイーツ", "dessert": "カフェ・スイーツ",
}


def fetch_center(lat, lng, radius_m=3000, timeout=120, retries=2):
    """Overpassで指定中心点・半径内の飲食店を取得。

    - GET 形式（POSTは 406 で弾くサーバーがある）
    - 各エンドポイントで指数バックオフでリトライ
    - サーバー過負荷時の 406/429/504 は一過性として扱う
    """
    amenities = "|".join(AMENITY_GENRE.keys())
    query = f"""
    [out:json][timeout:{timeout}];
    (
      node["amenity"~"^({amenities})$"](around:{radius_m},{lat},{lng});
      way["amenity"~"^({amenities})$"](around:{radius_m},{lat},{lng});
    );
    out center tags;
    """
    last_err = None
    for ep in OVERPASS_ENDPOINTS:
        for attempt in range(retries + 1):
            try:
                r = requests.get(
                    ep, params={"data": query},
                    headers={"User-Agent": UA},
                    timeout=timeout + 10,
                )
                if r.status_code in (406, 429, 504, 502, 503):
                    last_err = f"HTTP {r.status_code} from {ep}"
                    if attempt < retries:
                        time.sleep(3 * (2 ** attempt))
                    continue
                r.raise_for_status()
                return r.json().get("elements", [])
            except Exception as e:
                last_err = e
                if attempt < retries:
                    time.sleep(3 * (2 ** attempt))
    raise RuntimeError(f"All Overpass attempts failed: {last_err}")


def _get_latlng(el):
    """node は lat/lon、way は center.lat/lon を返す。"""
    if el.get("type") == "node":
        return el.get("lat"), el.get("lon")
    c = el.get("center") or {}
    return c.get("lat"), c.get("lon")


def _build_address(tags):
    """OSMのaddr:*タグから住所を組み立てる。"""
    parts = []
    for k in ["addr:province", "addr:city", "addr:ward", "addr:district",
              "addr:neighbourhood", "addr:street", "addr:housenumber",
              "addr:full"]:
        v = tags.get(k)
        if v and v not in parts:
            parts.append(v)
    if not parts:
        return ""
    return " ".join(parts)


def _genre(tags):
    """amenity + cuisine から日本語ジャンル名を決める。"""
    cuisine = (tags.get("cuisine") or "").lower().split(";")[0].strip()
    if cuisine in CUISINE_GENRE:
        return CUISINE_GENRE[cuisine]
    return AMENITY_GENRE.get(tags.get("amenity", ""), "その他")


def normalize_shop(el):
    """OSM要素を shops テーブル形式の dict に正規化。"""
    osm_id = f"{el.get('type')}/{el.get('id')}"
    sid = ID_PREFIX + osm_id
    tags = el.get("tags") or {}
    lat, lng = _get_latlng(el)
    name = (tags.get("name") or tags.get("name:ja") or tags.get("name:en")
            or "(名前未登録)")
    website = (tags.get("website") or tags.get("contact:website")
               or f"https://www.openstreetmap.org/{osm_id}")
    return {
        "id": sid,
        "name": name,
        "name_kana": tags.get("name:ja_kana") or tags.get("name:kana") or "",
        "address": _build_address(tags),
        "station_name": "",
        "lat": lat,
        "lng": lng,
        "genre_name": _genre(tags),
        "budget_name": "",
        "access": "",
        "pc_url": website,
        "private_room": "",
        "free_drink": "",
        "non_smoking": "",
        "course": "",
        "catch": tags.get("description", ""),
        "capacity": "",
        "party_capacity": "",
        "raw_json": json.dumps(el, ensure_ascii=False),
        "source": "osm",
    }


def upsert_shop(conn, el, now):
    """OSM要素を shops に UPSERT + judgements スタブ。1=新規 2=更新 3=同内容 0=スキップ。"""
    cols = normalize_shop(el)
    if "/None" in cols["id"] or cols["lat"] is None:
        return 0
    sid = cols["id"]
    row = conn.execute("SELECT raw_json FROM shops WHERE id = ?", (sid,)).fetchone()
    cols["last_seen_at"] = now
    cols["fetched_at"] = now
    if row:
        if row["raw_json"] == cols["raw_json"]:
            conn.execute("UPDATE shops SET last_seen_at = ? WHERE id = ?", (now, sid))
            return 3
        cols_sql = ", ".join(f"{k} = :{k}" for k in cols if k != "id")
        conn.execute(f"UPDATE shops SET {cols_sql} WHERE id = :id", cols)
        return 2
    cols["first_seen_at"] = now
    keys = ", ".join(cols.keys())
    ph = ", ".join(f":{k}" for k in cols)
    conn.execute(f"INSERT INTO shops ({keys}) VALUES ({ph})", cols)
    conn.execute(
        "INSERT OR IGNORE INTO judgements "
        "(shop_id, kaishoku_score, instagram_score, enriched_at) VALUES (?,0,0,?)",
        (sid, now),
    )
    return 1


def main():
    ap = argparse.ArgumentParser(description="OSM Overpass APIで23区の飲食店を取得しDB保存")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--centers", default="tokyo_centers.json")
    ap.add_argument("--max-centers", type=int, default=0)
    ap.add_argument("--radius-m", type=int, default=3000)
    args = ap.parse_args()

    centers = json.loads(Path(args.centers).read_text())
    if args.max_centers > 0:
        centers = centers[: args.max_centers]

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = dbmod.init_db(args.db)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO ingest_runs (started_at, centers) VALUES (?, ?)",
        (now, len(centers)),
    )
    run_id = cur.lastrowid

    seen_ids = set()
    new_total = upd_total = skip_total = 0
    for i, c in enumerate(centers, 1):
        print(f"[{i}/{len(centers)}] {c['ward']} {c['place']} ({c['lat']},{c['lng']})",
              file=sys.stderr)
        try:
            elements = fetch_center(c["lat"], c["lng"], args.radius_m)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            continue
        new_c = upd_c = skip_c = 0
        for el in elements:
            r = upsert_shop(conn, el, now)
            if r == 1: new_c += 1
            elif r == 2: upd_c += 1
            elif r == 0: skip_c += 1
            if r != 0:
                seen_ids.add(f"{el.get('type')}/{el.get('id')}")
        conn.commit()
        new_total += new_c; upd_total += upd_c; skip_total += skip_c
        print(f"  取得 {len(elements)}件 / 新規 {new_c} / 更新 {upd_c} / 座標欠落 {skip_c} / 累計 {len(seen_ids)}",
              file=sys.stderr)
        # Overpass はマナーとして1リクエスト後の間隔を空ける
        time.sleep(2)

    finished = dt.datetime.now(dt.timezone.utc).isoformat()
    conn.execute(
        "UPDATE ingest_runs SET finished_at=?, new_shops=?, updated_shops=? WHERE id=?",
        (finished, new_total, upd_total, run_id),
    )
    conn.commit()

    total_osm = conn.execute("SELECT COUNT(*) FROM shops WHERE source='osm'").fetchone()[0]
    total_all = conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0]
    print(
        f"\n=== ingest_osm 完了 ===\n"
        f"  中心: {len(centers)} / 新規: {new_total} / 更新: {upd_total} / スキップ: {skip_total}\n"
        f"  OSM店総数: {total_osm:,} / 全体DB: {total_all:,}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
