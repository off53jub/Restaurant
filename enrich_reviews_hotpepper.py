#!/usr/bin/env python3
"""HotPepper の口コミページ (/strJxxxx/report/) から口コミ本文・件数・シーン別件数を抽出。

既に shops にある HotPepper 店の pc_url から /report/ を取得する。
有料APIではなく、現行の enrich.py と同じ公開ページのスクレイピング。

reviews テーブル（source='hotpepper'）と、judgements への集計を保存。
"""
import argparse
import datetime as dt
import json
import re
import sys
import time
import concurrent.futures

import requests
from bs4 import BeautifulSoup

import db as dbmod

UA = ("Mozilla/5.0 (compatible; RestaurantFilter/0.1; personal-use; "
      "+https://example.local/restaurant-filter)")

SCENE_LABELS = {
    "会社の宴会": "company",
    "接待・会食": "kaishoku",
    "デート": "date",
    "友人・知人と": "friends",
    "家族・子供と": "family",
    "大人数の宴会": "party",
    "一人で": "solo",
}


def fetch(url, timeout=20, retries=2, backoff=1.5):
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt))
    return f"__ERROR__: {type(last).__name__}: {last}"


def parse_reports(html):
    """口コミページHTMLから件数・評価・シーン別・本文を抽出。"""
    out = {"total": None, "ratings": {}, "scenes": {}, "reviews": []}
    if not html or html.startswith("__ERROR__"):
        out["error"] = html
        return out
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    m = re.search(r"口コミ\s*[（(]\s*(\d+)\s*[)）]", text)
    if m:
        out["total"] = int(m.group(1))

    for label in ["総合", "料理・味", "雰囲気", "サービス", "CP", "ドリンク"]:
        mm = re.search(re.escape(label) + r"\s*([0-5]\.[0-9])", text)
        if mm:
            out["ratings"][label] = float(mm.group(1))

    # シーン別件数（リンクテキスト「接待・会食（4）」等）
    for a in soup.find_all("a", href=True):
        t = a.get_text(strip=True)
        sm = re.match(r"(.+?)\s*[（(](\d+)[)）]$", t)
        if sm and sm.group(1) in SCENE_LABELS:
            out["scenes"][SCENE_LABELS[sm.group(1)]] = int(sm.group(2))

    # 口コミ本文
    for el in soup.find_all(class_="reportText"):
        body = el.get_text(" ", strip=True)
        if len(body) >= 15:
            out["reviews"].append(body[:500])

    return out


def process_shop(shop_id, pc_url, delay=0.3):
    report_url = pc_url.split("?")[0].rstrip("/") + "/report/"
    html = fetch(report_url)
    time.sleep(delay)
    return shop_id, parse_reports(html)


def save(conn, shop_id, data, now):
    # judgements に集計を保存（列が無ければ migrate 済み前提）
    conn.execute(
        "UPDATE judgements SET hotpepper_review_count=?, hotpepper_review_scenes=? "
        "WHERE shop_id=?",
        (data.get("total"),
         json.dumps(data.get("scenes") or {}, ensure_ascii=False),
         shop_id),
    )
    # 口コミ本文を reviews テーブルへ（重複はUNIQUEで排除）
    for body in data.get("reviews") or []:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO reviews "
                "(shop_id, source, author, rating, text, fetched_at) "
                "VALUES (?, 'hotpepper', NULL, NULL, ?, ?)",
                (shop_id, body, now),
            )
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description="HotPepper口コミページから口コミ・件数を取得")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--max-age-days", type=int, default=90)
    ap.add_argument("--ids", nargs="+", help="特定店だけ")
    args = ap.parse_args()

    conn = dbmod.init_db(args.db)
    threshold = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=args.max_age_days)).isoformat()
    if args.ids:
        ph = ",".join("?" * len(args.ids))
        rows = list(conn.execute(
            f"SELECT id, pc_url FROM shops WHERE id IN ({ph})", args.ids))
    else:
        rows = list(conn.execute(
            "SELECT s.id, s.pc_url FROM shops s "
            "JOIN judgements j ON j.shop_id=s.id "
            "WHERE s.source='hotpepper' AND s.pc_url != '' "
            "AND (j.hotpepper_review_count IS NULL OR j.hp_review_fetched_at < ?)",
            (threshold,),
        ))
    if args.limit > 0:
        rows = rows[: args.limit]
    print(f"HotPepper口コミ取得対象: {len(rows)}件", file=sys.stderr)

    done = with_reviews = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(process_shop, r["id"], r["pc_url"], args.delay): r["id"]
                for r in rows}
        for fut in concurrent.futures.as_completed(futs):
            sid = futs[fut]
            try:
                _, data = fut.result()
            except Exception as e:
                data = {"error": str(e)}
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            save(conn, sid, data, now)
            conn.execute("UPDATE judgements SET hp_review_fetched_at=? WHERE shop_id=?",
                         (now, sid))
            done += 1
            if data.get("reviews"):
                with_reviews += 1
            if done % 50 == 0 or done == len(rows):
                conn.commit()
                print(f"  [{done}/{len(rows)}] 口コミ有={with_reviews} "
                      f"last_total={data.get('total')}", file=sys.stderr)
    conn.commit()
    print(f"\n=== 完了: {done}件処理 / 口コミ本文あり {with_reviews}件 ===", file=sys.stderr)


if __name__ == "__main__":
    main()
