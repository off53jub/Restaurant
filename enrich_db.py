#!/usr/bin/env python3
"""DBから enrich 対象を選んで判定結果を judgements に UPSERT。

対象選定:
  - judgements にレコードがない店（未 enrich）
  - enriched_at が --max-age-days 日より古い店
  - shops.fetched_at > judgements.enriched_at（再取得後）
"""
import argparse
import concurrent.futures
import datetime as dt
import json
import sys
from dataclasses import asdict
from pathlib import Path

import db as dbmod
from enrich import judge_shop, Judgement


def select_targets(conn, max_age_days, limit):
    """enrich 対象の shop 行を返す。"""
    threshold = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max_age_days)
    ).isoformat()
    q = """
    SELECT s.id, s.name, s.address, s.pc_url, s.raw_json
    FROM shops s
    LEFT JOIN judgements j ON j.shop_id = s.id
    WHERE j.shop_id IS NULL
       OR j.enriched_at < ?
       OR s.fetched_at > j.enriched_at
    ORDER BY j.enriched_at IS NULL DESC, j.enriched_at ASC
    """
    if limit > 0:
        q += f" LIMIT {int(limit)}"
    return list(conn.execute(q, (threshold,)))


def upsert_judgement(conn, shop_id, j: Judgement, now: str):
    d = asdict(j)
    cols = {
        "shop_id": shop_id,
        "drink_course_min_yen": d["drink_course_min_yen"],
        "drink_course_prices_json": json.dumps(d["drink_course_prices"]),
        "course_min_yen_any": d["course_min_yen_any"],
        "course_prices_any_json": json.dumps(d["course_prices_any"]),
        "fully_private_room": (
            None if d["fully_private_room"] is None else int(d["fully_private_room"])
        ),
        "smoking_at_seat": d["smoking_at_seat"],
        "smoking_evidence": d["smoking_evidence"],
        "private_evidence": d["private_evidence"],
        "kaishoku_score": d["kaishoku_score"],
        "kaishoku_hits_json": json.dumps(d["kaishoku_hits"], ensure_ascii=False),
        "mid_room_ok": None if d["mid_room_ok"] is None else int(d["mid_room_ok"]),
        "mid_room_evidence": d["mid_room_evidence"],
        "atmosphere_calm": d["atmosphere_calm"],
        "atmosphere_special": d["atmosphere_special"],
        "instagram_score": d["instagram_score"],
        "instagram_hits_json": json.dumps(d["instagram_hits"], ensure_ascii=False),
        "fetch_error": d["fetch_error"],
        "enriched_at": now,
    }
    keys = ", ".join(cols.keys())
    placeholders = ", ".join(f":{k}" for k in cols)
    sets = ", ".join(f"{k} = excluded.{k}" for k in cols if k != "shop_id")
    conn.execute(
        f"INSERT INTO judgements ({keys}) VALUES ({placeholders}) "
        f"ON CONFLICT(shop_id) DO UPDATE SET {sets}",
        cols,
    )


def main():
    ap = argparse.ArgumentParser(description="DB の shops を enrich して judgements に保存")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--max-age-days", type=int, default=30,
                    help="この日数より古い judgements は再 enrich (default: 30)")
    ap.add_argument("--limit", type=int, default=0, help=">0で先頭N件のみ")
    ap.add_argument("--concurrency", type=int, default=12)
    ap.add_argument("--delay", type=float, default=0.3)
    args = ap.parse_args()

    conn = dbmod.connect(args.db)
    targets = select_targets(conn, args.max_age_days, args.limit)
    print(f"enrich 対象: {len(targets)}件", file=sys.stderr)
    if not targets:
        return

    done = 0
    errors = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = {}
        for row in targets:
            shop_dict = json.loads(row["raw_json"])
            fut = ex.submit(judge_shop, shop_dict, args.delay)
            futures[fut] = row
        for fut in concurrent.futures.as_completed(futures):
            row = futures[fut]
            try:
                j = fut.result()
            except Exception as e:
                j = Judgement(fetch_error=f"{type(e).__name__}: {e}")
            if j.fetch_error:
                errors += 1
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            upsert_judgement(conn, row["id"], j, now)
            done += 1
            if done % 50 == 0 or done == len(targets):
                conn.commit()
                err_rate = errors / done * 100
                print(
                    f"  [{done}/{len(targets)}] err={errors}({err_rate:.0f}%) "
                    f"{row['name'][:24]} "
                    f"min={j.drink_course_min_yen} private={j.fully_private_room} "
                    f"calm={j.atmosphere_calm} ig={j.instagram_score}",
                    file=sys.stderr,
                )
    conn.commit()
    print(f"\n=== enrich 完了 (err {errors}/{done}) ===", file=sys.stderr)


if __name__ == "__main__":
    main()
