#!/usr/bin/env python3
"""YouTube Data API v3 で「店名」を検索し、動画本数・最大再生数を話題度プロキシに。

Instagram/TikTok は API 規約上リアルタイム話題度が取れないが、YouTube は公式 API
の無料枠（10,000 units/日）で動画検索でき、グルメ/食べ歩き動画のヒット数・再生数を
「ネットで話題か」の代替指標にできる。

セットアップ:
  1. Google Cloud Console で "YouTube Data API v3" を有効化（無料）
  2. APIキー発行 → .env に YOUTUBE_API_KEY=AIza...

コスト目安: search.list は 100 units/回。無料枠1万/日 = 100店/日まで。
  videos.list(統計) は 1 unit/回。

使い方:
  python enrich_youtube.py --visited-only
  python enrich_youtube.py --area 新宿 --limit 50
  python enrich_youtube.py --ids J003559227
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

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def search_videos(api_key, query, max_results=10, timeout=15):
    """店名でYouTube検索。動画IDリストと総ヒット概算を返す。"""
    params = {
        "key": api_key, "part": "snippet", "q": query,
        "type": "video", "maxResults": max_results,
        "regionCode": "JP", "relevanceLanguage": "ja",
    }
    r = requests.get(SEARCH_URL, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    total = int(data.get("pageInfo", {}).get("totalResults", 0))
    ids = [it["id"]["videoId"] for it in data.get("items", [])
           if it.get("id", {}).get("videoId")]
    titles = [it["snippet"]["title"] for it in data.get("items", [])]
    return total, ids, titles


def video_stats(api_key, video_ids, timeout=15):
    """動画IDの再生数合計・最大を返す。"""
    if not video_ids:
        return 0, 0
    r = requests.get(VIDEOS_URL, params={
        "key": api_key, "part": "statistics", "id": ",".join(video_ids),
    }, timeout=timeout)
    r.raise_for_status()
    views = []
    for it in r.json().get("items", []):
        v = it.get("statistics", {}).get("viewCount")
        if v is not None:
            views.append(int(v))
    return (max(views) if views else 0), (sum(views) if views else 0)


def is_relevant(titles, shop_name):
    """検索結果が本当にその店についてか粗く判定（誤ヒット抑制）。"""
    # 店名の主要部分（記号/支店名除去）がタイトルに含まれる動画が1つでもあるか
    core = shop_name.split()[0][:6] if shop_name else ""
    return any(core and core in t for t in titles)


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
    elif args.area:
        ors = " OR ".join("s.address LIKE ?" for _ in args.area)
        where.append(f"({ors})")
        params.extend(f"%{a}%" for a in args.area)
    where.append(
        "(s.id NOT IN (SELECT shop_id FROM judgements WHERE youtube_fetched_at >= ?))"
    )
    params.append(threshold)
    sql = f"SELECT s.id, s.name FROM shops s WHERE {' AND '.join(where)}"
    return list(conn.execute(sql, params))


def main():
    ap = argparse.ArgumentParser(description="YouTubeで店の話題度を取得")
    ap.add_argument("--db", default="db/shops.db")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--ids", nargs="+")
    src.add_argument("--visited-only", action="store_true")
    src.add_argument("--area", action="append")
    ap.add_argument("--max-age-days", type=int, default=90)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.2)
    ap.add_argument("--query-suffix", default="", help="検索語に付加（例: ' グルメ'）")
    args = ap.parse_args()

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        raise SystemExit("ERROR: YOUTUBE_API_KEY 未設定。"
                         "Google Cloud で YouTube Data API v3 有効化＋キー発行が必要。")

    conn = dbmod.init_db(args.db)
    targets = select_targets(conn, args)
    if args.limit > 0:
        targets = targets[: args.limit]
    print(f"YouTube対象: {len(targets)}件 (search.list 100units/件、無料枠1万/日)",
          file=sys.stderr)

    ok = hit = 0
    for i, t in enumerate(targets, 1):
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            q = f"{t['name']}{args.query_suffix}".strip()
            total, ids, titles = search_videos(api_key, q)
            if not is_relevant(titles, t["name"]):
                total, ids = 0, []  # 誤ヒットは0扱い
            top_views, _ = video_stats(api_key, ids[:5]) if ids else (0, 0)
            conn.execute(
                "UPDATE judgements SET youtube_video_count=?, youtube_top_views=?, "
                "youtube_fetched_at=? WHERE shop_id=?",
                (total, top_views, now, t["id"]),
            )
            ok += 1
            if total > 0:
                hit += 1
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 403:
                print(f"  APIクォータ超過 or キー無効で停止: {e}", file=sys.stderr)
                conn.commit()
                break
            conn.execute("UPDATE judgements SET youtube_fetched_at=? WHERE shop_id=?",
                         (now, t["id"]))
        if i % 20 == 0 or i == len(targets):
            conn.commit()
            print(f"  [{i}/{len(targets)}] hit={hit} last={t['name'][:24]} "
                  f"videos={total} views={top_views}", file=sys.stderr)
        time.sleep(args.delay)
    conn.commit()
    print(f"\n=== 完了: {ok}件処理 / 動画ヒット {hit}件 ===", file=sys.stderr)


if __name__ == "__main__":
    main()
