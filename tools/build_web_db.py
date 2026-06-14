#!/usr/bin/env python3
"""配信用に shops.db を縮小して shops-web.db.gz を作る (Phase D)。

Phase A の reviews/operational ドロップに加え、Phase D では:
  - shops.raw_json を分解して photo_url_l / photo_url_s を新規列に取り出す
  - shops の未使用列（生テキスト・運用日時）と raw_json をドロップ
  - social の未使用列（og_title, facebook_url ほか）をドロップ
  - 空 / 不要テーブルを削除
  - FTS5 トリガを削除（配布DBは read-only）
"""
import argparse
import gzip
import shutil
import sqlite3
import sys
from pathlib import Path


# UI で参照していない judgements 列。
JUDGEMENT_DROP = [
    "kaishoku_hits_json",
    "private_evidence",
    "smoking_evidence",
    "jsonld_json",
    "elevation_m",
    "photo_food_count",
    "photo_interior_count",
    "hp_photo_fetched_at",
    "corp_number",
    "corp_kind",
    "corp_fetched_at",
    "foursquare_id",
    "foursquare_popularity",
    "foursquare_fetched_at",
    "wayback_first_year",
    "wayback_last_year",
    "wayback_snapshot_count",
    "wayback_fetched_at",
    "youtube_top_views",
    "youtube_fetched_at",
    "hp_review_fetched_at",
    "bluesky_mention_count",
    "bluesky_fetched_at",
    "enriched_at",
    "ward",
]

# shops から落とす列。raw_json は backfill 後に削除する。
# name_kana は FTS5 の検索ターゲットなので Phase E 用に残す。
SHOPS_DROP = [
    "private_room",      # 生テキスト。judgements.fully_private_room を使う
    "free_drink",
    "non_smoking",
    "course",            # 生テキスト。drink_course_prices_json を使う
    "capacity",
    "party_capacity",
    "first_seen_at",
    "last_seen_at",
    "fetched_at",
    "raw_json",          # 最後に backfill 後ドロップ
]

# social から落とす列。og_image は ShopCard 写真フォールバックとして残す。
SOCIAL_DROP = [
    "og_title",
    "facebook_url",
    "twitter_url",
    "line_url",
    "youtube_url",
    "final_url",
    "fetched_at",
    "fetch_error",
]


def drop_columns(conn: sqlite3.Connection, table: str, cols: list[str]):
    existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for col in cols:
        if col in existing:
            try:
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
            except sqlite3.OperationalError as e:
                print(f"   skip drop {table}.{col}: {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="配信用 shops-web.db.gz を作る")
    ap.add_argument("--in", dest="src", default="db/shops.db")
    ap.add_argument("--out", default="db/shops-web.db.gz")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.exists():
        print(f"ERROR: input DB not found: {src}", file=sys.stderr)
        sys.exit(1)

    work = Path(args.out).with_suffix("")  # .gz を除いた .db パス
    work.parent.mkdir(parents=True, exist_ok=True)
    if work.exists():
        work.unlink()
    shutil.copy2(src, work)
    print(f"[1/6] copied {src} -> {work} ({work.stat().st_size/1024/1024:.1f} MB)", file=sys.stderr)

    conn = sqlite3.connect(work)
    conn.execute("PRAGMA foreign_keys=OFF")

    # 不要テーブルを削除
    for tbl in ("reviews", "ingest_runs", "google", "wiki"):
        conn.execute(f"DROP TABLE IF EXISTS {tbl}")

    # FTS5 トリガを削除（配布DBは read-only。DROP COLUMN を通すためにも必要）
    for trig in ("shops_ai", "shops_ad", "shops_au"):
        conn.execute(f"DROP TRIGGER IF EXISTS {trig}")

    # 落とす列を参照しているインデックスを先に削除
    for idx in ("shops_last_seen", "j_enriched"):
        conn.execute(f"DROP INDEX IF EXISTS {idx}")

    print("[2/6] dropped unused tables, triggers, indexes", file=sys.stderr)

    # raw_json -> photo_url_l / photo_url_s を抽出
    shops_cols = {r[1] for r in conn.execute("PRAGMA table_info(shops)").fetchall()}
    if "photo_url_l" not in shops_cols:
        conn.execute("ALTER TABLE shops ADD COLUMN photo_url_l TEXT")
    if "photo_url_s" not in shops_cols:
        conn.execute("ALTER TABLE shops ADD COLUMN photo_url_s TEXT")
    n = conn.execute(
        "UPDATE shops SET "
        "photo_url_l = json_extract(raw_json, '$.photo.pc.l'), "
        "photo_url_s = json_extract(raw_json, '$.photo.pc.s') "
        "WHERE raw_json IS NOT NULL"
    ).rowcount
    print(f"[3/6] backfilled photo URLs for {n} shops", file=sys.stderr)

    # 列ドロップ
    drop_columns(conn, "shops", SHOPS_DROP)
    drop_columns(conn, "judgements", JUDGEMENT_DROP)
    drop_columns(conn, "social", SOCIAL_DROP)
    conn.commit()
    print("[4/6] dropped unused columns", file=sys.stderr)

    conn.execute("VACUUM")
    conn.close()
    print(f"[5/6] vacuumed -> {work.stat().st_size/1024/1024:.1f} MB", file=sys.stderr)

    gz_path = Path(args.out)
    with open(work, "rb") as fin, gzip.open(gz_path, "wb", compresslevel=9) as fout:
        shutil.copyfileobj(fin, fout)
    work.unlink()
    print(f"[6/6] gzipped -> {gz_path} ({gz_path.stat().st_size/1024/1024:.1f} MB)", file=sys.stderr)


if __name__ == "__main__":
    main()
