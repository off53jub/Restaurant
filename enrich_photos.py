#!/usr/bin/env python3
"""HotPepperページ /photo/ から店舗関連写真の数を取得（G3）。

写真豊富＝店が宣伝に力入れてる、料理に自信ある、というシグナルになる。
食事/内観の正確な分類は HotPepperの構造上難しいので、
「店舗関連画像URLの本数」をシンプルなプロキシ指標として保存する。
"""
import argparse
import datetime as dt
import re
import sys
import time
import concurrent.futures

import requests
from bs4 import BeautifulSoup

import db as dbmod

UA = ("Mozilla/5.0 (compatible; RestaurantFilter/0.1; personal-use; "
      "+https://example.local/restaurant-filter)")
PHOTO_IMG_RE = re.compile(r"/shop|/food|/interior|/exterior|/menu", re.I)


def fetch_photo_counts(pc_url, timeout=15):
    """写真ページから (料理寄り画像数, 内観寄り画像数, 総数) を返す。"""
    url = pc_url.split("?")[0].rstrip("/") + "/photo/"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:80]}"}
    soup = BeautifulSoup(r.text, "html.parser")
    food = interior = total = 0
    seen = set()
    for img in soup.find_all("img", src=True):
        src = img["src"]
        if not PHOTO_IMG_RE.search(src):
            continue
        # 重複排除（imgsm/imgfp で同一画像複数解像度のことがある）
        key = re.sub(r"\?.*$", "", src.split("/")[-1])
        if key in seen:
            continue
        seen.add(key)
        total += 1
        if "/food" in src.lower() or "/menu" in src.lower():
            food += 1
        elif "/interior" in src.lower() or "/exterior" in src.lower() or "/shop" in src.lower():
            interior += 1
    return {"food": food, "interior": interior, "total": total}


def process_shop(shop_id, pc_url):
    return shop_id, fetch_photo_counts(pc_url)


def main():
    ap = argparse.ArgumentParser(description="HotPepper /photo/ から写真数を取得")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--max-age-days", type=int, default=90)
    args = ap.parse_args()

    conn = dbmod.init_db(args.db)
    threshold = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=args.max_age_days)).isoformat()
    sql = (
        "SELECT s.id, s.pc_url FROM shops s JOIN judgements j ON j.shop_id=s.id "
        "WHERE s.source='hotpepper' AND s.pc_url != '' "
        "AND (j.hp_photo_fetched_at IS NULL OR j.hp_photo_fetched_at < ?)"
    )
    if args.limit > 0:
        sql += f" LIMIT {int(args.limit)}"
    rows = list(conn.execute(sql, (threshold,)))
    print(f"写真取得対象: {len(rows):,}件", file=sys.stderr)

    done = with_food = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(process_shop, r["id"], r["pc_url"]): r["id"] for r in rows}
        for fut in concurrent.futures.as_completed(futs):
            sid = futs[fut]
            try:
                _, data = fut.result()
            except Exception as e:
                data = {"error": str(e)}
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            conn.execute(
                "UPDATE judgements SET photo_food_count=?, photo_interior_count=?, "
                "hp_photo_fetched_at=? WHERE shop_id=?",
                (data.get("food"), data.get("interior"), now, sid),
            )
            done += 1
            if data.get("food", 0) > 0 or data.get("interior", 0) > 0:
                with_food += 1
            if done % 100 == 0 or done == len(rows):
                conn.commit()
                print(f"  [{done}/{len(rows)}] 写真あり {with_food:,}", file=sys.stderr)
    conn.commit()
    print(f"\n=== 完了: {done}件 / 写真あり {with_food:,} ===", file=sys.stderr)


if __name__ == "__main__":
    main()
