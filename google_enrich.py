#!/usr/bin/env python3
"""Google Places API で店舗評価を取得しキャッシュする（任意機能）。

セットアップ:
  1. Google Cloud Console でプロジェクト作成 → "Places API" を有効化
  2. APIキー発行 → IPかリファラで利用制限
  3. .env に GOOGLE_PLACES_API_KEY=AIza... を追記

使い方:
  # クエリ結果の店だけ拡張（推奨。コスト最小）
  python query.py --preset kaishoku --format json | python google_enrich.py --from-stdin

  # 訪問済みの店だけ
  python google_enrich.py --visited-only

  # 特定IDだけ
  python google_enrich.py --ids J003559227 J001238039

  # 全店（高コスト警告。$32/1000リクエスト = 28k店で約$900）
  python google_enrich.py --all --confirm

料金目安(2026年): Text Search Pro $32/1000、IP制限・90日キャッシュで再課金回避。
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

import db as dbmod

load_dotenv()

# Google Places API (New) Text Search
ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
# 取得フィールド（コスト最小化のため最小限）
FIELD_MASK = "places.id,places.rating,places.userRatingCount,places.priceLevel,places.businessStatus,places.types"


def fetch_place(api_key, name, address, lat=None, lng=None, retries=2, backoff=2.0):
    """店名＋住所で検索し、最良一致の評価を返す。

    address が薄い OSM 店向けに、lat/lng が渡されたら locationBias を付けて精度UP。
    """
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    query_addr = (address or "").strip()
    body = {
        "textQuery": f"{name} {query_addr}".strip() if query_addr else name,
        "languageCode": "ja",
        "regionCode": "JP",
        "pageSize": 1,  # 最良1件のみ
    }
    if lat is not None and lng is not None:
        # 500m圏で最も近い一致を優先（OSM 由来の name 多義性対策）
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": float(lat), "longitude": float(lng)},
                "radius": 500.0,
            }
        }
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(ENDPOINT, headers=headers, json=body, timeout=20)
            if r.status_code == 429:  # rate limited
                time.sleep(backoff * (2 ** attempt))
                continue
            r.raise_for_status()
            places = r.json().get("places", [])
            if not places:
                return {"error": "no match"}
            p = places[0]
            return {
                "place_id": p.get("id"),
                "rating": p.get("rating"),
                "user_ratings_total": p.get("userRatingCount"),
                "price_level": _price_level_to_int(p.get("priceLevel")),
                "business_status": p.get("businessStatus"),
                "types_json": json.dumps(p.get("types", [])),
            }
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt))
    return {"error": f"{type(last_err).__name__}: {last_err}"}


def _price_level_to_int(s):
    """'PRICE_LEVEL_MODERATE' → 2 のように整数化。"""
    return {"PRICE_LEVEL_FREE": 0, "PRICE_LEVEL_INEXPENSIVE": 1,
            "PRICE_LEVEL_MODERATE": 2, "PRICE_LEVEL_EXPENSIVE": 3,
            "PRICE_LEVEL_VERY_EXPENSIVE": 4}.get(s)


def upsert(conn, shop_id, data, now):
    cols = {
        "shop_id": shop_id,
        "place_id": data.get("place_id"),
        "rating": data.get("rating"),
        "user_ratings_total": data.get("user_ratings_total"),
        "price_level": data.get("price_level"),
        "business_status": data.get("business_status"),
        "types_json": data.get("types_json"),
        "fetched_at": now,
        "fetch_error": data.get("error"),
    }
    keys = ", ".join(cols.keys())
    ph = ", ".join(f":{k}" for k in cols)
    sets = ", ".join(f"{k}=excluded.{k}" for k in cols if k != "shop_id")
    conn.execute(
        f"INSERT INTO google ({keys}) VALUES ({ph}) "
        f"ON CONFLICT(shop_id) DO UPDATE SET {sets}",
        cols,
    )


def select_targets(conn, args):
    threshold = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=args.max_age_days)).isoformat()
    where = ["1=1"]
    params = []
    if args.from_stdin:
        ids = [j["url"].split("strJ")[-1].split("/")[0]
               if "url" in j else None
               for j in json.load(sys.stdin)]
        ids = [f"J{i}" for i in ids if i]
        ph = ",".join("?" * len(ids))
        where.append(f"s.id IN ({ph})"); params.extend(ids)
    elif args.ids:
        ph = ",".join("?" * len(args.ids))
        where.append(f"s.id IN ({ph})"); params.extend(args.ids)
    elif args.visited_only:
        where.append("EXISTS (SELECT 1 FROM visits v WHERE v.shop_id = s.id)")
    elif args.osm_unique:
        # OSM固有(HotPepperと座標+名前で重複しない)＆連絡先ありの店だけ
        where.append("s.source='osm' AND s.lat IS NOT NULL")
        where.append(
            "NOT EXISTS (SELECT 1 FROM shops h WHERE h.source='hotpepper' "
            "AND h.lat IS NOT NULL "
            "AND ABS(h.lat - s.lat) < 0.0005 AND ABS(h.lng - s.lng) < 0.0005)"
        )
    elif args.all:
        if not args.confirm:
            raise SystemExit("--all は --confirm 必須（高コスト）")
    else:
        raise SystemExit("--from-stdin / --ids / --visited-only / --osm-unique / --all のいずれかを指定")

    # キャッシュ: max_age 内に正常取得済みは除外
    where.append(
        "NOT EXISTS (SELECT 1 FROM google g WHERE g.shop_id = s.id "
        "AND g.fetched_at >= ? AND (g.fetch_error IS NULL OR g.fetch_error=''))"
    )
    params.append(threshold)
    sql = f"SELECT s.id, s.name, s.address, s.lat, s.lng FROM shops s WHERE {' AND '.join(where)}"
    return list(conn.execute(sql, params))


def main():
    ap = argparse.ArgumentParser(description="Google Places APIで評価取得")
    ap.add_argument("--db", default="db/shops.db")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--ids", nargs="+")
    src.add_argument("--visited-only", action="store_true")
    src.add_argument("--from-stdin", action="store_true",
                     help="query.py --format json の出力をパイプ")
    src.add_argument("--osm-unique", action="store_true",
                     help="OSM固有(HPと重複しない)個人店だけGoogle照合")
    src.add_argument("--all", action="store_true", help="高コスト警告")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--max-age-days", type=int, default=90)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.1, help="リクエスト間スリープ秒")
    args = ap.parse_args()

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        raise SystemExit("ERROR: GOOGLE_PLACES_API_KEY が .env に未設定。"
                         "Google Cloud Console で Places API 有効化＋キー発行が必要。")

    conn = dbmod.init_db(args.db)
    targets = select_targets(conn, args)
    if args.limit > 0:
        targets = targets[: args.limit]
    print(f"Google拡張対象: {len(targets)}件 (キャッシュ済除外)", file=sys.stderr)
    if args.all and not args.limit:
        est_cost = len(targets) * 0.032
        ok = input(f"推定コスト ${est_cost:.2f}。続行? [y/N] ").strip().lower()
        if ok != "y":
            return

    ok_n = err_n = 0
    for i, t in enumerate(targets, 1):
        data = fetch_place(api_key, t["name"], t["address"], t["lat"], t["lng"])
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        upsert(conn, t["id"], data, now)
        if data.get("error"):
            err_n += 1
        else:
            ok_n += 1
        if i % 20 == 0 or i == len(targets):
            conn.commit()
            print(f"  [{i}/{len(targets)}] ok={ok_n} err={err_n} {t['name'][:30]} "
                  f"★{data.get('rating')} ({data.get('user_ratings_total')})", file=sys.stderr)
        time.sleep(args.delay)
    conn.commit()
    print(f"\n=== 完了: ok={ok_n} / err={err_n} ===", file=sys.stderr)


if __name__ == "__main__":
    main()
