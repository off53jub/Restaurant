#!/usr/bin/env python3
"""店の公式サイトを fetch して SNS リンクと OG メタ情報を抽出する。

「SNSで話題か」のリアルタイム取得は Instagram/TikTok API の規約上不可能。
代替として「公式アカウントへの導線」「公式説明・写真」までを自動取得する。

対象:
  - OSM の website / contact:website が直接 instagram.com 等を指す場合
  - 公式サイトの場合は HTML から SNS リンクと OG メタを抽出
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

import db as dbmod

load_dotenv()

UA = "restaurant-filter/0.1"

# プラットフォーム判定
SNS_PATTERNS = {
    "instagram_url":  re.compile(r"https?://(?:www\.)?instagram\.com/[^\s\"'<>?#]+", re.I),
    "tiktok_url":     re.compile(r"https?://(?:www\.)?tiktok\.com/@?[^\s\"'<>?#]+", re.I),
    "facebook_url":   re.compile(r"https?://(?:www\.|m\.)?facebook\.com/[^\s\"'<>?#]+", re.I),
    "twitter_url":    re.compile(r"https?://(?:www\.|mobile\.)?(?:twitter|x)\.com/[^\s\"'<>?#]+", re.I),
    "line_url":       re.compile(r"https?://(?:lin\.ee|page\.line\.me|liff\.line\.me)/[^\s\"'<>?#]+", re.I),
    "youtube_url":    re.compile(r"https?://(?:www\.)?youtube\.com/(?:@|channel/|c/|user/)[^\s\"'<>?#]+", re.I),
}

# Facebookのアプリ系・SDK系URLは除外
EXCLUDE_PATTERNS = [
    re.compile(r"facebook\.com/(tr|plugins|sharer|dialog|connect|fbevents)", re.I),
    re.compile(r"facebook\.com/?$", re.I),
    re.compile(r"instagram\.com/?$", re.I),
    re.compile(r"instagram\.com/(p|reel|stories|explore|accounts)/", re.I),
    re.compile(r"twitter\.com/(intent|share|home|i)(/|$)", re.I),
    re.compile(r"twitter\.com/?$", re.I),
]


def is_excluded(url):
    return any(p.search(url) for p in EXCLUDE_PATTERNS)


def categorize_url(url):
    """URL から（プラットフォーム名, 正規化URL）を返す。"""
    if is_excluded(url):
        return None, None
    for key, pat in SNS_PATTERNS.items():
        if pat.search(url):
            # クエリパラメータ除去
            return key, url.split("?")[0].rstrip("/")
    return None, None


def extract_from_html(html):
    """HTMLから SNS URL と OG メタを抽出。"""
    soup = BeautifulSoup(html, "html.parser")
    found = {}

    # <a href> 内のSNSリンク
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("//"):
            href = "https:" + href
        key, url = categorize_url(href)
        if key and key not in found:
            found[key] = url

    # OGP メタタグ
    for prop in ["og:title", "og:description", "og:image"]:
        m = soup.find("meta", attrs={"property": prop})
        if m and m.get("content"):
            k = prop.replace("og:", "og_")
            found[k] = m["content"].strip()[:500]

    # title フォールバック
    if "og_title" not in found and soup.title and soup.title.string:
        found["og_title"] = soup.title.string.strip()[:200]

    return found


def fetch_and_extract(url, timeout=15):
    """URL を fetch して SNS と OG を抽出。直接 SNS URL なら fetch せず判定。"""
    if not url:
        return {"fetch_error": "no url"}
    # 直接 instagram.com 等を指している場合
    key, normalized = categorize_url(url)
    if key:
        return {key: normalized, "final_url": normalized}

    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout,
                         allow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        return {"fetch_error": f"{type(e).__name__}: {str(e)[:120]}"}

    result = extract_from_html(r.text)
    result["final_url"] = r.url
    return result


def get_official_website(raw_json_str, source):
    """raw_json から「公式サイトと思われるURL」を取り出す。

    OSM: tags.website / contact:website
    HotPepper: API応答に urls.mobile / urls.pc があるが、これは HotPepper の
               店舗ページなので、catch などから外部URLは抜けない。スキップ。
    """
    raw = json.loads(raw_json_str)
    if source == "osm":
        tags = raw.get("tags") or {}
        return tags.get("website") or tags.get("contact:website")
    # HotPepperは公式サイトを raw に持たないので未対応
    return None


def select_targets(conn, args):
    """対象 shop_id 一覧を返す。"""
    threshold = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=args.max_age_days)).isoformat()
    where = []
    params = []
    if args.ids:
        ph = ",".join("?" * len(args.ids))
        where.append(f"s.id IN ({ph})"); params.extend(args.ids)
    elif args.visited_only:
        where.append("EXISTS (SELECT 1 FROM visits v WHERE v.shop_id = s.id)")
    elif args.osm_with_website:
        where.append("s.source='osm'")
    else:
        raise SystemExit("--ids / --visited-only / --osm-with-website のいずれかを指定")

    where.append(
        "NOT EXISTS (SELECT 1 FROM social so WHERE so.shop_id = s.id "
        "AND so.fetched_at >= ? AND (so.fetch_error IS NULL OR so.fetch_error=''))"
    )
    params.append(threshold)
    sql = f"SELECT s.id, s.name, s.raw_json, s.source FROM shops s WHERE {' AND '.join(where)}"
    rows = list(conn.execute(sql, params))
    # website がある店だけ実際の対象に
    filtered = []
    for r in rows:
        ws = get_official_website(r["raw_json"], r["source"])
        if ws:
            filtered.append((r["id"], r["name"], ws))
    return filtered


def upsert(conn, shop_id, data, now):
    cols = {
        "shop_id": shop_id,
        "instagram_url": data.get("instagram_url"),
        "tiktok_url": data.get("tiktok_url"),
        "facebook_url": data.get("facebook_url"),
        "twitter_url": data.get("twitter_url"),
        "line_url": data.get("line_url"),
        "youtube_url": data.get("youtube_url"),
        "og_title": data.get("og_title"),
        "og_description": data.get("og_description"),
        "og_image": data.get("og_image"),
        "final_url": data.get("final_url"),
        "fetched_at": now,
        "fetch_error": data.get("fetch_error"),
    }
    keys = ", ".join(cols.keys())
    ph = ", ".join(f":{k}" for k in cols)
    sets = ", ".join(f"{k}=excluded.{k}" for k in cols if k != "shop_id")
    conn.execute(
        f"INSERT INTO social ({keys}) VALUES ({ph}) "
        f"ON CONFLICT(shop_id) DO UPDATE SET {sets}",
        cols,
    )


def main():
    ap = argparse.ArgumentParser(description="公式サイトからSNS+OG情報を取得")
    ap.add_argument("--db", default="db/shops.db")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--ids", nargs="+")
    src.add_argument("--visited-only", action="store_true")
    src.add_argument("--osm-with-website", action="store_true",
                     help="OSM店でwebsiteタグありを全件処理")
    ap.add_argument("--max-age-days", type=int, default=90)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.3)
    args = ap.parse_args()

    conn = dbmod.init_db(args.db)
    targets = select_targets(conn, args)
    if args.limit > 0:
        targets = targets[: args.limit]
    print(f"social拡張対象: {len(targets)}件", file=sys.stderr)

    ok = sns = errs = 0
    for i, (sid, name, ws) in enumerate(targets, 1):
        data = fetch_and_extract(ws)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        upsert(conn, sid, data, now)
        if data.get("fetch_error"):
            errs += 1
        else:
            ok += 1
            if any(data.get(k) for k in
                   ["instagram_url","tiktok_url","facebook_url","twitter_url"]):
                sns += 1
        if i % 30 == 0 or i == len(targets):
            conn.commit()
            print(f"  [{i}/{len(targets)}] ok={ok} sns={sns} err={errs} "
                  f"{name[:30]} ig={data.get('instagram_url','')[:50] if data.get('instagram_url') else ''}",
                  file=sys.stderr)
        time.sleep(args.delay)
    conn.commit()
    print(f"\n=== 完了: ok={ok} (うちSNS発見={sns}) / err={errs} ===", file=sys.stderr)


if __name__ == "__main__":
    main()
