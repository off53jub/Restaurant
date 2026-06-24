#!/usr/bin/env python3
"""Wikidata SPARQL で老舗・有名店の Wikipedia 概要を取得する（無料・無制限）。

カバー率は限定的（カバーされるのはWikipedia記事のある有名店のみ、推定1-5%）だが、
当たれば質の高い情報が取れる：店の歴史・創業年・有名な料理・受賞歴など。

例:
  python enrich_wiki.py --visited-only
  python enrich_wiki.py --ids J003559227 J001238039
  python enrich_wiki.py --all-hotpepper --limit 100
"""
import argparse
import datetime as dt
import json
import sys
import time

import requests

import db as dbmod

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIPEDIA_API_JA = "https://ja.wikipedia.org/w/api.php"
UA = "restaurant-filter/0.1 (wikidata enrichment)"


def search_wikidata(name, timeout=15):
    """店名で Wikidata を検索。"店" の付加 / 「東京」付加でフォールバック検索。

    返り値: {"wikidata_id": "Qxxx", "label": "...", "description": "..."} or None
    """
    for q in [name, f"{name} 東京", f"{name} レストラン"]:
        try:
            r = requests.get(
                "https://www.wikidata.org/w/api.php",
                params={
                    "action": "wbsearchentities", "search": q,
                    "language": "ja", "uselang": "ja",
                    "type": "item", "limit": 5, "format": "json",
                },
                headers={"User-Agent": UA}, timeout=timeout,
            )
            r.raise_for_status()
            results = r.json().get("search") or []
            for hit in results:
                desc = (hit.get("description") or "").lower()
                # 飲食店っぽいか粗いフィルタ
                if any(k in desc for k in ["restaurant", "レストラン", "料亭", "飲食",
                                            "ホテル", "hotel", "ramen", "寿司",
                                            "izakaya", "居酒屋", "カフェ", "cafe"]):
                    return {
                        "wikidata_id": hit["id"],
                        "label": hit.get("label", ""),
                        "description": hit.get("description", ""),
                    }
        except Exception:
            continue
    return None


def fetch_wikipedia_summary(wikidata_id, timeout=15):
    """Wikidata ID から ja.wikipedia のサイトリンクを引き、記事の冒頭抜粋を取得。"""
    try:
        r = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities", "ids": wikidata_id,
                "props": "sitelinks", "sitefilter": "jawiki",
                "format": "json",
            },
            headers={"User-Agent": UA}, timeout=timeout,
        )
        r.raise_for_status()
        ent = (r.json().get("entities") or {}).get(wikidata_id, {})
        title = ((ent.get("sitelinks") or {}).get("jawiki") or {}).get("title")
        if not title:
            return {"wikipedia_ja_url": None, "summary": None}
        # ja.wikipedia REST API で要約を取得
        wpr = requests.get(
            f"https://ja.wikipedia.org/api/rest_v1/page/summary/{title}",
            headers={"User-Agent": UA}, timeout=timeout,
        )
        if wpr.status_code == 404:
            return {"wikipedia_ja_url": f"https://ja.wikipedia.org/wiki/{title}",
                    "summary": None}
        wpr.raise_for_status()
        s = wpr.json()
        return {
            "wikipedia_ja_url": s.get("content_urls", {}).get("desktop", {}).get("page"),
            "summary": (s.get("extract") or "")[:600],
        }
    except Exception:
        return {"wikipedia_ja_url": None, "summary": None}


def select_targets(conn, args):
    threshold = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=args.max_age_days)).isoformat()
    where = []
    params = []
    if args.ids:
        ph = ",".join("?" * len(args.ids))
        where.append(f"s.id IN ({ph})"); params.extend(args.ids)
    elif args.visited_only:
        where.append("EXISTS (SELECT 1 FROM visits v WHERE v.shop_id = s.id)")
    elif args.all_hotpepper:
        where.append("s.source='hotpepper'")
    else:
        raise SystemExit("--ids / --visited-only / --all-hotpepper のいずれかを指定")

    where.append(
        "NOT EXISTS (SELECT 1 FROM wiki w WHERE w.shop_id=s.id "
        "AND w.fetched_at >= ?)"
    )
    params.append(threshold)
    sql = f"SELECT s.id, s.name FROM shops s WHERE {' AND '.join(where)}"
    return list(conn.execute(sql, params))


def upsert(conn, shop_id, data, now):
    cols = {
        "shop_id": shop_id,
        "wikidata_id": data.get("wikidata_id"),
        "label": data.get("label"),
        "description": data.get("description"),
        "wikipedia_ja_url": data.get("wikipedia_ja_url"),
        "summary": data.get("summary"),
        "fetched_at": now,
    }
    keys = ", ".join(cols.keys())
    ph = ", ".join(f":{k}" for k in cols)
    sets = ", ".join(f"{k}=excluded.{k}" for k in cols if k != "shop_id")
    conn.execute(
        f"INSERT INTO wiki ({keys}) VALUES ({ph}) "
        f"ON CONFLICT(shop_id) DO UPDATE SET {sets}",
        cols,
    )


def main():
    ap = argparse.ArgumentParser(description="Wikidata/Wikipedia から店情報を補完")
    ap.add_argument("--db", default="db/shops.db")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--ids", nargs="+")
    src.add_argument("--visited-only", action="store_true")
    src.add_argument("--all-hotpepper", action="store_true")
    ap.add_argument("--max-age-days", type=int, default=180)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=1.0,
                    help="Wikidata は 1req/sec 程度のマナー")
    args = ap.parse_args()

    conn = dbmod.init_db(args.db)
    targets = select_targets(conn, args)
    if args.limit > 0:
        targets = targets[: args.limit]
    print(f"Wiki拡張対象: {len(targets)}件", file=sys.stderr)

    found_n = 0
    for i, t in enumerate(targets, 1):
        wd = search_wikidata(t["name"])
        if wd:
            wp = fetch_wikipedia_summary(wd["wikidata_id"])
            wd.update(wp)
            found_n += 1
        else:
            wd = {}
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        upsert(conn, t["id"], wd, now)
        if i % 20 == 0 or i == len(targets):
            conn.commit()
            print(f"  [{i}/{len(targets)}] found={found_n} {t['name'][:30]} "
                  f"→ {wd.get('wikidata_id','-')}",
                  file=sys.stderr)
        time.sleep(args.delay)
    conn.commit()
    print(f"\n=== 完了: ヒット {found_n}/{len(targets)} ===", file=sys.stderr)


if __name__ == "__main__":
    main()
