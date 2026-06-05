#!/usr/bin/env python3
"""Bluesky検索APIで店名メンション数を取得（G7、無料・認証不要）。

Twitter/X の代替として Bluesky の公開検索APIで「店名」が含まれる投稿数を
話題度プロキシに。レート制限は緩いが、各リクエスト後に少しsleep。

注: 完全公開APIなのでキー不要。
"""
import argparse
import datetime as dt
import sys
import time

import requests

import db as dbmod

ENDPOINT = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
UA = "restaurant-filter/0.1"


def search_mentions(query, timeout=15):
    try:
        r = requests.get(ENDPOINT, params={"q": query, "limit": 25},
                         headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        d = r.json()
        return len(d.get("posts") or [])
    except Exception as e:
        return -1  # エラー印


def select_targets(conn, args):
    threshold = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=args.max_age_days)).isoformat()
    where = ["s.source='hotpepper'"]
    params = []
    if args.ids:
        where = [f"s.id IN ({','.join('?'*len(args.ids))})"]
        params.extend(args.ids)
    elif args.visited_only:
        where.append("EXISTS (SELECT 1 FROM visits v WHERE v.shop_id=s.id)")
    elif args.popular_only:
        # HotPepper口コミ件数の多い人気店だけ
        where.append("EXISTS (SELECT 1 FROM judgements jj WHERE jj.shop_id=s.id "
                     "AND jj.hotpepper_review_count >= ?)")
        params.append(args.popular_threshold)
    elif args.area:
        ors = " OR ".join("s.address LIKE ?" for _ in args.area)
        where.append(f"({ors})")
        params.extend(f"%{a}%" for a in args.area)
    where.append("(s.id NOT IN (SELECT shop_id FROM judgements "
                 "WHERE bluesky_fetched_at >= ?))")
    params.append(threshold)
    return list(conn.execute(
        f"SELECT s.id, s.name FROM shops s WHERE {' AND '.join(where)}", params,
    ))


def main():
    ap = argparse.ArgumentParser(description="Blueskyで店名メンション数を取得")
    ap.add_argument("--db", default="db/shops.db")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--ids", nargs="+")
    src.add_argument("--visited-only", action="store_true")
    src.add_argument("--area", action="append")
    src.add_argument("--popular-only", action="store_true",
                     help="HotPepper口コミN件以上の人気店だけ")
    ap.add_argument("--popular-threshold", type=int, default=100,
                    help="--popular-only の閾値（既定100）")
    ap.add_argument("--max-age-days", type=int, default=30)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()

    conn = dbmod.init_db(args.db)
    targets = select_targets(conn, args)
    if args.limit > 0:
        targets = targets[: args.limit]
    print(f"Bluesky検索対象: {len(targets)}件", file=sys.stderr)

    ok = hit = 0
    for i, t in enumerate(targets, 1):
        n = search_mentions(t["name"])
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        conn.execute(
            "UPDATE judgements SET bluesky_mention_count=?, bluesky_fetched_at=? "
            "WHERE shop_id=?",
            (n if n >= 0 else None, now, t["id"]),
        )
        ok += 1
        if n > 0:
            hit += 1
        if i % 30 == 0 or i == len(targets):
            conn.commit()
            print(f"  [{i}/{len(targets)}] mention>0={hit}", file=sys.stderr)
        time.sleep(args.delay)
    conn.commit()
    print(f"\n=== 完了: {ok}件 / メンションあり {hit}件 ===", file=sys.stderr)


if __name__ == "__main__":
    main()
