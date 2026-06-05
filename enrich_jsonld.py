#!/usr/bin/env python3
"""公式サイトから JSON-LD (schema.org Restaurant) を抽出（G5、無料）。

公式サイトに `<script type="application/ld+json">` で構造化された情報があれば、
営業時間/メニュー/価格帯/電話/sameAs(SNS) を取得して judgements.jsonld_json に保存。
enrich_social.py で取得済みの final_url をベースに走らせる。
"""
import argparse
import datetime as dt
import json
import sys
import time
import concurrent.futures

import requests
from bs4 import BeautifulSoup

import db as dbmod

UA = "restaurant-filter/0.1"


def extract_jsonld(html):
    """HTML中の <script type="application/ld+json"> を全部パース。
    Restaurant/FoodEstablishment/LocalBusiness 型を優先して抜き出す。
    """
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for s in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(s.string or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        # @graph 配列を平坦化
        items = data if isinstance(data, list) else (data.get("@graph") or [data])
        for it in items:
            if not isinstance(it, dict):
                continue
            tp = it.get("@type") or ""
            if isinstance(tp, list):
                tp = " ".join(tp)
            if any(k in tp for k in ("Restaurant", "FoodEstablishment",
                                     "LocalBusiness", "CafeOrCoffeeShop", "Bar")):
                candidates.append(it)
    if not candidates:
        return None
    # 最も情報量の多いものを返す
    return max(candidates, key=lambda x: len(json.dumps(x)))


def fetch_and_extract(url, timeout=15):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:80]}"}
    j = extract_jsonld(r.text)
    return {"jsonld": j} if j else {"empty": True}


def main():
    ap = argparse.ArgumentParser(description="公式サイトからJSON-LDを抽出")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--max-age-days", type=int, default=180)
    args = ap.parse_args()

    conn = dbmod.init_db(args.db)
    threshold = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=args.max_age_days)).isoformat()
    rows = list(conn.execute(
        "SELECT s.id, so.final_url FROM shops s "
        "JOIN social so ON so.shop_id=s.id "
        "JOIN judgements j ON j.shop_id=s.id "
        "WHERE so.final_url IS NOT NULL AND so.fetch_error IS NULL "
        "AND (j.jsonld_json IS NULL)",
    ))
    if args.limit > 0:
        rows = rows[: args.limit]
    print(f"JSON-LD対象: {len(rows):,}件", file=sys.stderr)

    done = found = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(fetch_and_extract, r["final_url"]): r["id"] for r in rows}
        for fut in concurrent.futures.as_completed(futs):
            sid = futs[fut]
            try:
                data = fut.result()
            except Exception as e:
                data = {"error": str(e)}
            if data.get("jsonld"):
                conn.execute(
                    "UPDATE judgements SET jsonld_json=? WHERE shop_id=?",
                    (json.dumps(data["jsonld"], ensure_ascii=False), sid),
                )
                found += 1
            done += 1
            if done % 50 == 0 or done == len(rows):
                conn.commit()
                print(f"  [{done}/{len(rows)}] JSON-LDあり {found:,}",
                      file=sys.stderr)
    conn.commit()
    print(f"\n=== 完了: {done}件 / JSON-LD取得 {found:,}件 ===", file=sys.stderr)


if __name__ == "__main__":
    main()
