#!/usr/bin/env python3
"""Wayback Machine APIで店ページの過去スナップショットを調べる（H1、無料・認証なし）。

各店のHotPepperページ(pc_url) または公式サイト(social.final_url) について、
- 最古スナップショット年: いつから営業/掲載してるか（老舗判定）
- 最新スナップショット年: 直近もアクティブか（閉店リスク把握）
- 取得済みスナップショット数: 何年分の記録があるか

を取得して judgements に保存する。
"""
import argparse
import datetime as dt
import sys
import time

import requests

import db as dbmod

ENDPOINT = "https://archive.org/wayback/available"
UA = "restaurant-filter/0.1"
# 5年刻みで確認（細かすぎるとAPIに失礼）
PROBE_YEARS = [2010, 2014, 2018, 2020, 2022, 2024, 2026]


def check_year(url, year, timeout=10):
    """指定 timestamp に最も近い snapshot があれば dict を返す。"""
    try:
        r = requests.get(ENDPOINT, params={"url": url, "timestamp": f"{year}0101"},
                         headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        snap = (r.json().get("archived_snapshots") or {}).get("closest")
        return snap if snap and snap.get("available") else None
    except Exception:
        return None


def fetch_history(url, delay=0.4):
    """URLの過去履歴を集計。"""
    earliest = latest = None
    snap_count = 0
    for y in PROBE_YEARS:
        snap = check_year(url, y)
        time.sleep(delay)
        if not snap:
            continue
        snap_count += 1
        # 実際の snapshot timestamp の最初の4桁が実年
        ts = snap.get("timestamp", "")
        try:
            real_year = int(ts[:4])
        except (ValueError, TypeError):
            real_year = y
        if earliest is None or real_year < earliest:
            earliest = real_year
        if latest is None or real_year > latest:
            latest = real_year
    return {"first_year": earliest, "last_year": latest, "snapshot_count": snap_count}


def select_targets(conn, args):
    threshold = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=args.max_age_days)).isoformat()
    where = ["s.pc_url != ''"]
    params = []
    if args.ids:
        where = [f"s.id IN ({','.join('?'*len(args.ids))})"]
        params.extend(args.ids)
    elif args.visited_only:
        where.append("EXISTS (SELECT 1 FROM visits v WHERE v.shop_id=s.id)")
    elif args.popular_only:
        where.append("EXISTS (SELECT 1 FROM judgements jj WHERE jj.shop_id=s.id "
                     "AND jj.hotpepper_review_count >= ?)")
        params.append(args.popular_threshold)
    else:
        raise SystemExit("--ids / --visited-only / --popular-only のいずれかを指定")
    where.append("(s.id NOT IN (SELECT shop_id FROM judgements "
                 "WHERE wayback_fetched_at >= ?))")
    params.append(threshold)
    return list(conn.execute(
        f"SELECT s.id, s.name, s.pc_url FROM shops s WHERE {' AND '.join(where)}",
        params,
    ))


def main():
    ap = argparse.ArgumentParser(description="Wayback Machineで店ページの履歴を取得")
    ap.add_argument("--db", default="db/shops.db")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--ids", nargs="+")
    src.add_argument("--visited-only", action="store_true")
    src.add_argument("--popular-only", action="store_true",
                     help="HotPepper口コミN件以上の人気店だけ")
    ap.add_argument("--popular-threshold", type=int, default=200)
    ap.add_argument("--max-age-days", type=int, default=365)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.4)
    args = ap.parse_args()

    conn = dbmod.init_db(args.db)
    targets = select_targets(conn, args)
    if args.limit > 0:
        targets = targets[: args.limit]
    print(f"Wayback対象: {len(targets)}件（各店7年探索）", file=sys.stderr)

    ok = hit = 0
    for i, t in enumerate(targets, 1):
        h = fetch_history(t["pc_url"], delay=args.delay)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        conn.execute(
            "UPDATE judgements SET wayback_first_year=?, wayback_last_year=?, "
            "wayback_snapshot_count=?, wayback_fetched_at=? WHERE shop_id=?",
            (h["first_year"], h["last_year"], h["snapshot_count"], now, t["id"]),
        )
        ok += 1
        if h["snapshot_count"] > 0:
            hit += 1
        if i % 10 == 0 or i == len(targets):
            conn.commit()
            print(f"  [{i}/{len(targets)}] hit={hit} {t['name'][:24]} "
                  f"{h['first_year']}-{h['last_year']} ({h['snapshot_count']}年分)",
                  file=sys.stderr)
    conn.commit()
    print(f"\n=== 完了: {ok}件 / 履歴あり {hit}件 ===", file=sys.stderr)


if __name__ == "__main__":
    main()
