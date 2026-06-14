#!/usr/bin/env python3
"""配信用に shops.db を縮小して shops-web.db.gz を作る (Phase A 暫定版)。

Phase A: reviews テーブル/不要列を落として VACUUM するだけ。
  - reviews テーブル丸ごと削除（口コミは詳細画面の Phase E で別途 lazy fetch）
  - judgements の重い JSON 列のうち UI 不要なものを削除
  - ingest_runs (運用ログ) を削除
Phase D で raw_json を分解して photo URL 等を新規列に取り出す予定（未実装）。
"""
import argparse
import gzip
import shutil
import sqlite3
import sys
from pathlib import Path


# UI に不要な列（Phase A）。`judgements` テーブルから DROP COLUMN する。
DROP_JUDGEMENT_COLS = [
    "kaishoku_hits_json",
    "instagram_hits_json",  # コメント: ShopCard で使うので Phase A は残す
    "private_evidence",
    "smoking_evidence",
    "mid_room_evidence",  # コメント: 5-8名個室の根拠表示で使うので残す
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
    "bluesky_mention_count",
    "bluesky_fetched_at",
    "wayback_first_year",
    "wayback_last_year",
    "wayback_snapshot_count",
    "wayback_fetched_at",
    "youtube_video_count",
    "youtube_top_views",
    "youtube_fetched_at",
    "hp_review_fetched_at",
]
# Phase A で UI から本当に参照しないもののみ残し、根拠系は ShopCard 用に残す
ACTUALLY_DROP = [
    "kaishoku_hits_json",     # ShopCard で kaishoku_hits は使っていない
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
]


def main():
    ap = argparse.ArgumentParser(description="配信用 shops-web.db.gz を作る")
    ap.add_argument("--in", dest="src", default="db/shops.db")
    ap.add_argument("--out", default="db/shops-web.db.gz")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.exists():
        print(f"ERROR: input DB not found: {src}", file=sys.stderr)
        sys.exit(1)

    # ワーキングコピーで作業（VACUUM 用）
    work = Path(args.out).with_suffix("")  # .gz を除いた .db パス
    work.parent.mkdir(parents=True, exist_ok=True)
    if work.exists():
        work.unlink()
    shutil.copy2(src, work)
    print(f"[1/4] copied {src} -> {work} ({work.stat().st_size/1024/1024:.1f} MB)", file=sys.stderr)

    conn = sqlite3.connect(work)
    conn.execute("PRAGMA foreign_keys=OFF")

    # reviews / ingest_runs を削除
    for tbl in ("reviews", "ingest_runs"):
        conn.execute(f"DROP TABLE IF EXISTS {tbl}")

    # judgements の不要列を SQLite 3.35+ の DROP COLUMN で削除
    jcols = {r[1] for r in conn.execute("PRAGMA table_info(judgements)").fetchall()}
    for col in ACTUALLY_DROP:
        if col in jcols:
            try:
                conn.execute(f"ALTER TABLE judgements DROP COLUMN {col}")
            except sqlite3.OperationalError as e:
                print(f"   skip drop {col}: {e}", file=sys.stderr)

    conn.commit()
    print("[2/4] dropped unused tables and columns", file=sys.stderr)

    conn.execute("VACUUM")
    conn.close()
    print(f"[3/4] vacuumed -> {work.stat().st_size/1024/1024:.1f} MB", file=sys.stderr)

    # gzip
    gz_path = Path(args.out)
    with open(work, "rb") as fin, gzip.open(gz_path, "wb", compresslevel=9) as fout:
        shutil.copyfileobj(fin, fout)
    work.unlink()
    print(f"[4/4] gzipped -> {gz_path} ({gz_path.stat().st_size/1024/1024:.1f} MB)", file=sys.stderr)


if __name__ == "__main__":
    main()
