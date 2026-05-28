#!/usr/bin/env python3
"""HotPepper API から 東京23区の店舗を取得して SQLite に UPSERT する。"""
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

API_URL = "https://webservice.recruit.co.jp/hotpepper/gourmet/v1/"
RANGE_3KM = 5  # HotPepper API range code


def fetch_center(api_key, lat, lng, range_code=RANGE_3KM):
    """単一中心点から全件ページング取得。"""
    shops = []
    start = 1
    count = 100
    while True:
        params = {
            "key": api_key,
            "lat": lat,
            "lng": lng,
            "range": range_code,
            "count": count,
            "start": start,
            "format": "json",
        }
        resp = requests.get(API_URL, params=params, timeout=30)
        resp.raise_for_status()
        results = resp.json().get("results", {})
        page = results.get("shop", [])
        shops.extend(page)
        total = int(results.get("results_available", 0))
        if start + count > total or not page:
            break
        start += count
        time.sleep(0.2)
    return shops


def upsert_shop(conn, s, now):
    """1店舗を shops に UPSERT。新規=1, 既存更新=2 を返す。"""
    shop_id = s.get("id")
    if not shop_id:
        return 0
    row = conn.execute("SELECT id FROM shops WHERE id = ?", (shop_id,)).fetchone()
    cols = {
        "id": shop_id,
        "name": s.get("name", ""),
        "name_kana": s.get("name_kana", ""),
        "address": s.get("address", ""),
        "station_name": s.get("station_name", ""),
        "lat": s.get("lat"),
        "lng": s.get("lng"),
        "genre_name": s.get("genre", {}).get("name", ""),
        "budget_name": s.get("budget", {}).get("name", ""),
        "access": s.get("access", ""),
        "pc_url": s.get("urls", {}).get("pc", ""),
        "private_room": s.get("private_room", ""),
        "free_drink": s.get("free_drink", ""),
        "non_smoking": s.get("non_smoking", ""),
        "course": s.get("course", ""),
        "catch": s.get("catch", ""),
        "capacity": s.get("capacity", ""),
        "party_capacity": s.get("party_capacity", ""),
        "raw_json": json.dumps(s, ensure_ascii=False),
        "last_seen_at": now,
        "fetched_at": now,
    }
    if row:
        cols_sql = ", ".join(f"{k} = :{k}" for k in cols if k != "id")
        conn.execute(f"UPDATE shops SET {cols_sql} WHERE id = :id", cols)
        return 2
    cols["first_seen_at"] = now
    keys = ", ".join(cols.keys())
    placeholders = ", ".join(f":{k}" for k in cols)
    conn.execute(f"INSERT INTO shops ({keys}) VALUES ({placeholders})", cols)
    return 1


def main():
    ap = argparse.ArgumentParser(description="23区の店舗を HotPepper API から取得しDB保存")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--centers", default="tokyo_centers.json")
    ap.add_argument("--max-centers", type=int, default=0, help=">0で先頭N中心のみ（試走用）")
    ap.add_argument("--range", type=int, default=RANGE_3KM, choices=[1, 2, 3, 4, 5])
    args = ap.parse_args()

    api_key = os.environ.get("HOTPEPPER_API_KEY")
    if not api_key:
        print("ERROR: HOTPEPPER_API_KEY 未設定", file=sys.stderr)
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
        print(
            f"[{i}/{len(centers)}] {c['ward']} {c['place']} ({c['lat']},{c['lng']})",
            file=sys.stderr,
        )
        try:
            shops = fetch_center(api_key, c["lat"], c["lng"], args.range)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            continue
        new_c = upd_c = 0
        for s in shops:
            sid = s.get("id")
            if not sid:
                continue
            seen_ids.add(sid)
            r = upsert_shop(conn, s, now)
            if r == 1:
                new_c += 1
            elif r == 2:
                upd_c += 1
        conn.commit()
        new_total += new_c
        upd_total += upd_c
        print(
            f"  取得 {len(shops)}件 / 新規 {new_c} / 更新 {upd_c} / 累計ユニーク {len(seen_ids)}",
            file=sys.stderr,
        )
        time.sleep(0.3)

    finished = dt.datetime.now(dt.timezone.utc).isoformat()
    conn.execute(
        "UPDATE ingest_runs SET finished_at=?, new_shops=?, updated_shops=? WHERE id=?",
        (finished, new_total, upd_total, run_id),
    )
    conn.commit()

    total_in_db = conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0]
    print(
        f"\n=== ingest 完了 ===\n"
        f"  中心: {len(centers)}\n"
        f"  ユニーク取得: {len(seen_ids)}\n"
        f"  新規: {new_total}\n"
        f"  更新: {upd_total}\n"
        f"  DB総数: {total_in_db}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
