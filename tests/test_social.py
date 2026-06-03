"""enrich_social.py のテスト。HTML/URL パースのみ（外部fetchはしない）。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as dbmod
import enrich_social


def test_categorize_instagram_direct():
    k, u = enrich_social.categorize_url("https://www.instagram.com/foo_shop/")
    assert k == "instagram_url"
    assert u == "https://www.instagram.com/foo_shop"


def test_categorize_tiktok():
    k, _ = enrich_social.categorize_url("https://www.tiktok.com/@foo")
    assert k == "tiktok_url"


def test_categorize_twitter_or_x():
    assert enrich_social.categorize_url("https://twitter.com/foo")[0] == "twitter_url"
    assert enrich_social.categorize_url("https://x.com/foo")[0] == "twitter_url"


def test_categorize_facebook():
    assert enrich_social.categorize_url("https://facebook.com/mypage")[0] == "facebook_url"


def test_categorize_line():
    assert enrich_social.categorize_url("https://lin.ee/abc123")[0] == "line_url"


def test_excludes_fb_plugins_and_share():
    assert enrich_social.categorize_url("https://facebook.com/sharer.php?u=...")[0] is None
    assert enrich_social.categorize_url("https://facebook.com/tr?id=...")[0] is None
    assert enrich_social.categorize_url("https://twitter.com/intent/tweet")[0] is None
    assert enrich_social.categorize_url("https://instagram.com/p/abc123")[0] is None


def test_extract_from_html_picks_sns_and_ogp():
    html = """<html><head>
        <meta property="og:title" content="居酒屋ZZ">
        <meta property="og:description" content="落ち着いた個室">
        <meta property="og:image" content="https://example.com/cover.jpg">
        </head><body>
        <a href="https://instagram.com/zz_official">IG</a>
        <a href="https://www.tiktok.com/@zz_tt">TT</a>
        <a href="https://facebook.com/sharer.php?u=foo">share</a>
        </body></html>"""
    out = enrich_social.extract_from_html(html)
    assert out["instagram_url"] == "https://instagram.com/zz_official"
    assert out["tiktok_url"] == "https://www.tiktok.com/@zz_tt"
    assert "facebook_url" not in out  # sharer は除外
    assert out["og_title"] == "居酒屋ZZ"
    assert out["og_description"] == "落ち着いた個室"
    assert out["og_image"] == "https://example.com/cover.jpg"


def test_extract_title_fallback_when_no_og():
    html = "<html><head><title>店名タイトル</title></head><body></body></html>"
    out = enrich_social.extract_from_html(html)
    assert out["og_title"] == "店名タイトル"


def test_get_official_website_osm():
    rj = '{"tags": {"website": "https://example.com"}}'
    assert enrich_social.get_official_website(rj, "osm") == "https://example.com"
    rj2 = '{"tags": {"contact:website": "https://x.com"}}'
    assert enrich_social.get_official_website(rj2, "osm") == "https://x.com"


def test_get_official_website_hotpepper_returns_none():
    rj = '{"urls": {"pc": "https://www.hotpepper.jp/strJ001/"}}'
    assert enrich_social.get_official_website(rj, "hotpepper") is None


def test_fetch_and_extract_direct_sns_skips_http():
    out = enrich_social.fetch_and_extract("https://www.instagram.com/cafe_xyz/")
    assert out["instagram_url"] == "https://www.instagram.com/cafe_xyz"
    assert "fetch_error" not in out


def test_upsert_writes_to_social_table():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    now = "2026-05-01T00:00:00+00:00"
    # ダミー shop を入れる
    conn.execute(
        "INSERT INTO shops(id,name,address,raw_json,source,first_seen_at,last_seen_at,fetched_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        ("osm:node/1", "テスト店", "東京", "{}", "osm", now, now, now),
    )
    conn.commit()
    enrich_social.upsert(conn, "osm:node/1", {
        "instagram_url": "https://instagram.com/test_shop",
        "og_title": "テスト店 公式",
        "final_url": "https://example.com",
    }, now)
    conn.commit()
    r = conn.execute("SELECT * FROM social WHERE shop_id=?", ("osm:node/1",)).fetchone()
    assert r["instagram_url"] == "https://instagram.com/test_shop"
    assert r["og_title"] == "テスト店 公式"
    assert r["tiktok_url"] is None  # 未指定はNULL
