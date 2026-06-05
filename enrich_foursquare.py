#!/usr/bin/env python3
"""Foursquare Places API で店の人気度＋tipsを取得（G1、要キー・無料枠あり）。

無料枠: 月1000リクエストまで。tips（短い口コミ）と popularity が取れる。

セットアップ:
  https://foursquare.com/developers/ でアカウント作成
  .env に FSQ_API_KEY=fsqXXXX を追記
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

import db as dbmod

load_dotenv()

SEARCH_URL = "https://api.foursquare.com/v3/places/search"
TIPS_URL = "https://api.foursquare.com/v3/places/{}/tips"
DETAIL_URL = "https://api.foursquare.com/v3/places/{}"


def search_place(api_key, name, lat, lng, timeout=15):
    h = {"Authorization": api_key, "Accept": "application/json"}
    params = {"query": name, "ll": f"{lat},{lng}", "radius": 200, "limit": 1}
    r = requests.get(SEARCH_URL, headers=h, params=params, timeout=timeout)
    r.raise_for_status()
    results = r.json().get("results") or []
    return results[0] if results else None


def fetch_tips(api_key, fsq_id, timeout=15):
    h = {"Authorization": api_key}
    r = requests.get(TIPS_URL.format(fsq_id), headers=h, params={"limit": 5},
                     timeout=timeout)
    r.raise_for_status()
    return [{"text": t.get("text"), "created_at": t.get("created_at")}
            for t in r.json()]


def fetch_detail(api_key, fsq_id, timeout=15):
    h = {"Authorization": api_key, "Accept": "application/json"}
    r = requests.get(DETAIL_URL.format(fsq_id), headers=h,
                     params={"fields": "popularity,rating,stats"}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def select_targets(conn, args):
    threshold = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=args.max_age_days)).isoformat()
    where = ["s.lat IS NOT NULL"]
    params = []
    if args.ids:
        where = [f"s.id IN ({','.join('?'*len(args.ids))})"]
        params.extend(args.ids)
    elif args.visited_only:
        where.append("EXISTS (SELECT 1 FROM visits v WHERE v.shop_id=s.id)")
    else:
        raise SystemExit("--ids / --visited-only を指定")
    where.append("(s.id NOT IN (SELECT shop_id FROM judgements "
                 "WHERE foursquare_fetched_at >= ?))")
    params.append(threshold)
    return list(conn.execute(
        f"SELECT s.id, s.name, s.lat, s.lng FROM shops s WHERE {' AND '.join(where)}",
        params,
    ))


def main():
    ap = argparse.ArgumentParser(description="Foursquare Places で店の人気度を取得")
    ap.add_argument("--db", default="db/shops.db")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--ids", nargs="+")
    src.add_argument("--visited-only", action="store_true")
    ap.add_argument("--max-age-days", type=int, default=180)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.2)
    args = ap.parse_args()

    api_key = os.environ.get("FSQ_API_KEY")
    if not api_key:
        raise SystemExit("ERROR: FSQ_API_KEY 未設定。"
                         "https://foursquare.com/developers/ でキー発行(無料枠あり)")

    conn = dbmod.init_db(args.db)
    targets = select_targets(conn, args)
    if args.limit > 0:
        targets = targets[: args.limit]
    print(f"Foursquare対象: {len(targets)}件（無料枠1000リク/月）", file=sys.stderr)

    ok = hit = 0
    for i, t in enumerate(targets, 1):
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            place = search_place(api_key, t["name"], t["lat"], t["lng"])
        except Exception as e:
            place = None
            print(f"  search失敗: {e}", file=sys.stderr)
        if place:
            fsq_id = place.get("fsq_id")
            try:
                detail = fetch_detail(api_key, fsq_id)
                pop = detail.get("popularity")
            except Exception:
                pop = None
            try:
                tips = fetch_tips(api_key, fsq_id)
            except Exception:
                tips = []
            conn.execute(
                "UPDATE judgements SET foursquare_id=?, foursquare_popularity=?, "
                "foursquare_fetched_at=? WHERE shop_id=?",
                (fsq_id, pop, now, t["id"]),
            )
            # tips を reviews テーブルへ
            for tip in tips:
                if tip.get("text"):
                    conn.execute(
                        "INSERT OR IGNORE INTO reviews(shop_id, source, text, fetched_at)"
                        " VALUES(?,'foursquare',?,?)",
                        (t["id"], tip["text"], now),
                    )
            hit += 1
        else:
            conn.execute(
                "UPDATE judgements SET foursquare_fetched_at=? WHERE shop_id=?",
                (now, t["id"]),
            )
        ok += 1
        if i % 20 == 0 or i == len(targets):
            conn.commit()
            print(f"  [{i}/{len(targets)}] hit={hit} {t['name'][:24]}",
                  file=sys.stderr)
        time.sleep(args.delay)
    conn.commit()
    print(f"\n=== 完了: {ok}件 / Foursquare特定 {hit}件 ===", file=sys.stderr)


if __name__ == "__main__":
    main()
