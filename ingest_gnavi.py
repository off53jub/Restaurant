#!/usr/bin/env python3
"""ぐるなび RestSearchAPI v3 から店舗を取得して SQLite に UPSERT する。

HotPepper(ingest.py) と相互補完。重複は ID プレフィックス 'g:' で分離管理。

セットアップ:
  1. https://api.gnavi.co.jp/api/manage/ で API キー発行（無料）
  2. .env に GNAVI_API_KEY=xxxx を追記

使い方:
  python ingest_gnavi.py                # 23区全中心
  python ingest_gnavi.py --max-centers 3  # 試走
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

API_URL = "https://api.gnavi.co.jp/RestSearchAPI/v3/"
# range_code: 1=300m, 2=500m, 3=1km, 4=2km, 5=3km
RANGE_3KM = 5

ID_PREFIX = "g:"


def fetch_center(api_key, lat, lng, range_code=RANGE_3KM):
    """ぐるなびAPIを1中心点で全件ページング取得。"""
    shops = []
    offset = 1
    per_page = 100
    while True:
        params = {
            "keyid": api_key,
            "latitude": lat,
            "longitude": lng,
            "range": range_code,
            "hit_per_page": per_page,
            "offset_page": offset,
            "format": "json",
        }
        resp = requests.get(API_URL, params=params, timeout=30)
        if resp.status_code == 404 and "no_record" in resp.text:
            break  # ぐるなびは0件で404を返すことがある
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            # 認証エラー等は即座に停止
            raise RuntimeError(f"Gnavi API error: {data['error']}")
        page = data.get("rest", []) or []
        shops.extend(page)
        total = int(data.get("total_hit_count", 0))
        if not page or offset * per_page >= total:
            break
        offset += 1
        time.sleep(0.2)
    return shops


def normalize_shop(g):
    """ぐるなびの店舗1件を shops テーブル形式の dict に正規化。"""
    sid = ID_PREFIX + str(g.get("id"))
    # 緯度経度は文字列で来ることがある
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return {
        "id": sid,
        "name": g.get("name", ""),
        "name_kana": g.get("name_kana", ""),
        "address": g.get("address", ""),
        "station_name": "",  # ぐるなびにはstation_nameの単一フィールドが無い
        "lat": _f(g.get("latitude")),
        "lng": _f(g.get("longitude")),
        "genre_name": g.get("category", ""),
        "budget_name": (
            f"{g.get('budget','')}円" if g.get("budget") else ""
        ),
        "access": (g.get("access", {}) or {}).get("line", "")
                  + " "
                  + (g.get("access", {}) or {}).get("station", "")
                  + " "
                  + (g.get("access", {}) or {}).get("walk", "") if isinstance(g.get("access"), dict) else "",
        "pc_url": g.get("url", ""),
        "private_room": "",
        "free_drink": "",
        "non_smoking": "",
        "course": "",
        "catch": g.get("pr", {}).get("pr_short", "") if isinstance(g.get("pr"), dict) else "",
        "capacity": str(g.get("capacity", "")),
        "party_capacity": str(g.get("party_capacity", "")),
        "raw_json": json.dumps(g, ensure_ascii=False),
        "source": "gnavi",
    }


def upsert_shop(conn, g, now):
    """1店舗を shops に UPSERT。新規=1, 更新=2, 同内容=3。
    また、stub の judgements 行も同時に確保（クエリで JOIN しても落ちないように）。
    """
    cols = normalize_shop(g)
    if not cols["id"] or cols["id"] == ID_PREFIX + "None":
        return 0
    sid = cols["id"]
    row = conn.execute("SELECT raw_json FROM shops WHERE id = ?", (sid,)).fetchone()
    cols["last_seen_at"] = now
    cols["fetched_at"] = now
    if row:
        if row["raw_json"] == cols["raw_json"]:
            conn.execute(
                "UPDATE shops SET last_seen_at = ? WHERE id = ?", (now, sid)
            )
            return 3
        cols_sql = ", ".join(f"{k} = :{k}" for k in cols if k != "id")
        conn.execute(f"UPDATE shops SET {cols_sql} WHERE id = :id", cols)
        return 2
    cols["first_seen_at"] = now
    keys = ", ".join(cols.keys())
    ph = ", ".join(f":{k}" for k in cols)
    conn.execute(f"INSERT INTO shops ({keys}) VALUES ({ph})", cols)
    # ぐるなび店は enrich せずスタブ judgement のみ作成
    conn.execute(
        "INSERT OR IGNORE INTO judgements "
        "(shop_id, kaishoku_score, instagram_score, enriched_at) "
        "VALUES (?, 0, 0, ?)",
        (sid, now),
    )
    return 1


def main():
    ap = argparse.ArgumentParser(description="ぐるなびAPIで23区の店舗を取得しDB保存")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--centers", default="tokyo_centers.json")
    ap.add_argument("--max-centers", type=int, default=0)
    ap.add_argument("--range", type=int, default=RANGE_3KM, choices=[1, 2, 3, 4, 5])
    args = ap.parse_args()

    api_key = os.environ.get("GNAVI_API_KEY")
    if not api_key:
        print("ERROR: GNAVI_API_KEY が .env に未設定。"
              "https://api.gnavi.co.jp/api/manage/ でキー発行(無料)。",
              file=sys.stderr)
        sys.exit(1)

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
    new_total = 0
    upd_total = 0

    for i, c in enumerate(centers, 1):
        print(f"[{i}/{len(centers)}] {c['ward']} {c['place']} ({c['lat']},{c['lng']})",
              file=sys.stderr)
        try:
            shops = fetch_center(api_key, c["lat"], c["lng"], args.range)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            continue
        new_c = upd_c = 0
        for g in shops:
            r = upsert_shop(conn, g, now)
            if r == 1:
                new_c += 1
            elif r == 2:
                upd_c += 1
            if r != 0:
                seen_ids.add(ID_PREFIX + str(g.get("id")))
        conn.commit()
        new_total += new_c
        upd_total += upd_c
        print(f"  取得 {len(shops)}件 / 新規 {new_c} / 更新 {upd_c} / 累計ユニーク {len(seen_ids)}",
              file=sys.stderr)
        time.sleep(0.3)

    finished = dt.datetime.now(dt.timezone.utc).isoformat()
    conn.execute(
        "UPDATE ingest_runs SET finished_at=?, new_shops=?, updated_shops=? WHERE id=?",
        (finished, new_total, upd_total, run_id),
    )
    conn.commit()

    total_gnavi = conn.execute("SELECT COUNT(*) FROM shops WHERE source='gnavi'").fetchone()[0]
    total_all = conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0]
    print(
        f"\n=== ingest_gnavi 完了 ===\n"
        f"  中心: {len(centers)} / 新規: {new_total} / 更新: {upd_total}\n"
        f"  ぐるなび店総数: {total_gnavi:,} / 全体DB: {total_all:,}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
