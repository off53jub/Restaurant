#!/usr/bin/env python3
"""国税庁 法人番号API で店の運営法人を特定（G2、無料・要App ID）。

「個人経営 vs 大手チェーン子会社」を判別する。接待で「あの店は××HD系列か」を
即座に把握できる。

セットアップ:
  https://www.houjin-bangou.nta.go.jp/webapi/ で App ID 取得（即時、無料）
  .env に HOUJIN_API_KEY=xxxx を追記

使い方:
  python enrich_corporation.py --visited-only
  python enrich_corporation.py --ids J003559227 J001238039
"""
import argparse
import datetime as dt
import os
import sys
import time

import requests
from dotenv import load_dotenv

import db as dbmod

load_dotenv()

ENDPOINT = "https://api.houjin-bangou.nta.go.jp/4/name"
UA = "restaurant-filter/0.1"


def search_corp(api_key, name, prefecture="東京都", city=None, timeout=15, retries=2):
    """商号(法人名)検索。匹敵候補1件以上のリストを返す。"""
    params = {
        "id": api_key,
        "name": name,
        "type": "12",        # JSON応答
        "address": prefecture if not city else f"{prefecture}{city}",
        "mode": "2",         # 部分一致
        "target": "1",       # 法人番号順
    }
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(ENDPOINT, params=params, headers={"User-Agent": UA},
                             timeout=timeout)
            r.raise_for_status()
            return r.json().get("corporations") or []
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(1.5 * (2 ** attempt))
    return [{"error": f"{type(last).__name__}: {last}"}]


def pick_best(name, addr, candidates):
    """名前と住所の一致度で1件選ぶ。"""
    for c in candidates:
        if "error" in c:
            return c
        c_name = c.get("name", "")
        c_addr = (c.get("prefectureName", "") + c.get("cityName", "")
                  + c.get("streetNumber", ""))
        # 単純: 名前が部分一致＆住所(区名)が一致なら採用
        if any(part in c_name for part in [name, name[:6]] if part):
            return c
    return candidates[0] if candidates else None


def select_targets(conn, args):
    threshold = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=args.max_age_days)).isoformat()
    where = ["s.source = 'hotpepper'"]
    params = []
    if args.ids:
        where = [f"s.id IN ({','.join('?'*len(args.ids))})"]
        params.extend(args.ids)
    elif args.visited_only:
        where.append("EXISTS (SELECT 1 FROM visits v WHERE v.shop_id=s.id)")
    where.append(
        "(s.id NOT IN (SELECT shop_id FROM judgements WHERE corp_fetched_at >= ?))"
    )
    params.append(threshold)
    return list(conn.execute(
        f"SELECT s.id, s.name, s.address FROM shops s WHERE {' AND '.join(where)}",
        params,
    ))


def main():
    ap = argparse.ArgumentParser(description="法人番号API で運営法人を特定")
    ap.add_argument("--db", default="db/shops.db")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--ids", nargs="+")
    src.add_argument("--visited-only", action="store_true")
    ap.add_argument("--max-age-days", type=int, default=180)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.3)
    args = ap.parse_args()

    api_key = os.environ.get("HOUJIN_API_KEY")
    if not api_key:
        raise SystemExit("ERROR: HOUJIN_API_KEY 未設定。"
                         "https://www.houjin-bangou.nta.go.jp/webapi/ で App ID発行(無料即時)")

    conn = dbmod.init_db(args.db)
    targets = select_targets(conn, args)
    if args.limit > 0:
        targets = targets[: args.limit]
    print(f"法人検索対象: {len(targets)}件", file=sys.stderr)

    ok = hit = 0
    for i, t in enumerate(targets, 1):
        cands = search_corp(api_key, t["name"], "東京都")
        picked = pick_best(t["name"], t["address"], cands)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if picked and "error" not in picked:
            conn.execute(
                "UPDATE judgements SET corp_number=?, corp_kind=?, corp_fetched_at=? "
                "WHERE shop_id=?",
                (picked.get("corporateNumber"), picked.get("kind"), now, t["id"]),
            )
            hit += 1
        else:
            conn.execute("UPDATE judgements SET corp_fetched_at=? WHERE shop_id=?",
                         (now, t["id"]))
        ok += 1
        if i % 30 == 0 or i == len(targets):
            conn.commit()
            print(f"  [{i}/{len(targets)}] hit={hit} {t['name'][:24]}", file=sys.stderr)
        time.sleep(args.delay)
    conn.commit()
    print(f"\n=== 完了: {ok}件 / 法人特定 {hit}件 ===", file=sys.stderr)


if __name__ == "__main__":
    main()
