"""reviews.py のテスト。Google APIは呼ばず、DB操作と要約ロジックのみ。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as dbmod
import google_enrich
import reviews as reviews_mod


def _make_db_with_shop_and_reviews():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    now = "2026-05-29T00:00:00+00:00"
    conn.execute(
        "INSERT INTO shops(id,name,address,raw_json,source,first_seen_at,last_seen_at,fetched_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        ("S1", "テスト和食店", "東京都港区赤坂1-1-1", "{}", "hotpepper", now, now, now),
    )
    # google レーティング
    conn.execute(
        "INSERT INTO google(shop_id, rating, user_ratings_total, fetched_at) "
        "VALUES (?, 4.3, 120, ?)",
        ("S1", now),
    )
    # レビュー3件
    for author, rating, text in [
        ("田中", 5, "個室で落ち着いて食事できました。料理も美味しく接客も丁寧でした。"),
        ("佐藤", 4, "コスパは普通だが雰囲気は良い。デートにも使える。"),
        ("鈴木", 2, "予約が取りにくく、待ち時間も長かった。料理は普通。"),
    ]:
        conn.execute(
            "INSERT INTO reviews(shop_id, source, author, rating, text, fetched_at) "
            "VALUES (?, 'google', ?, ?, ?, ?)",
            ("S1", author, rating, text, now),
        )
    conn.commit()
    return conn


def test_extract_themes_finds_categories():
    texts = [
        "個室で落ち着いて食事、料理も美味しい",
        "接客が丁寧、デートに最適",
        "予約が取りにくい",
    ]
    hits, examples = reviews_mod.extract_themes(texts)
    assert "料理の質" in hits
    assert "雰囲気" in hits
    assert "接客" in hits
    assert "シーン適合" in hits
    assert "予約・混雑" in hits
    # 例示が拾えている
    assert all(isinstance(ex, str) and ex for ex in examples.values())


def test_pick_representative_returns_top_low_mid():
    rvs = [
        {"rating": 5, "text": "a" * 50, "author": "x", "relative_time": ""},
        {"rating": 4, "text": "b" * 50, "author": "y", "relative_time": ""},
        {"rating": 3, "text": "c" * 50, "author": "z", "relative_time": ""},
        {"rating": 2, "text": "d" * 50, "author": "w", "relative_time": ""},
        {"rating": 1, "text": "e" * 50, "author": "v", "relative_time": ""},
    ]
    picks = reviews_mod.pick_representative(rvs, 3)
    ratings = sorted([p["rating"] for p in picks], reverse=True)
    # 高/低/中 の構成: 最高(5) と 最低(1) と中庸 が含まれる
    assert 5 in ratings and 1 in ratings


def test_pick_representative_filters_short_text():
    rvs = [
        {"rating": 5, "text": "短い", "author": "x", "relative_time": ""},
        {"rating": 4, "text": "x" * 50, "author": "y", "relative_time": ""},
    ]
    picks = reviews_mod.pick_representative(rvs, 3)
    assert all(len(p["text"]) >= 30 for p in picks)


def test_fetch_reviews_returns_sorted_by_rating():
    conn = _make_db_with_shop_and_reviews()
    rvs = reviews_mod.fetch_reviews(conn, "S1")
    assert len(rvs) == 3
    # rating DESC, then length DESC
    assert rvs[0]["rating"] == 5


def test_fetch_shops_by_area():
    conn = _make_db_with_shop_and_reviews()
    shops = reviews_mod.fetch_shops_by_area(conn, ["赤坂"], rating_min=4.0, limit=10)
    assert len(shops) == 1
    assert shops[0]["name"] == "テスト和食店"


def test_format_shop_section_includes_themes_and_reps():
    conn = _make_db_with_shop_and_reviews()
    shop = dict(conn.execute(
        "SELECT s.id, s.name, s.address, g.rating AS google_rating, "
        "g.user_ratings_total AS google_reviews "
        "FROM shops s LEFT JOIN google g ON g.shop_id=s.id WHERE s.id='S1'"
    ).fetchone())
    rvs = reviews_mod.fetch_reviews(conn, "S1")
    out = reviews_mod.format_shop_section(shop, rvs)
    assert "テーマ集計" in out
    assert "料理の質" in out
    assert "代表的な口コミ" in out
    assert "★★★★★" in out


# ---- google_enrich のレビュー保存ロジック ----

def test_parse_reviews_normalizes_fields():
    raw = [
        {
            "rating": 5,
            "text": {"text": "美味しかった", "languageCode": "ja"},
            "authorAttribution": {"displayName": "田中"},
            "relativePublishTimeDescription": "2 months ago",
            "publishTime": "2025-03-15T10:00:00Z",
        }
    ]
    out = google_enrich._parse_reviews(raw)
    assert out[0]["author"] == "田中"
    assert out[0]["text"] == "美味しかった"
    assert out[0]["rating"] == 5
    assert out[0]["language"] == "ja"


def test_upsert_writes_reviews_with_unique_dedup():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    now = "2026-05-29T00:00:00+00:00"
    conn.execute(
        "INSERT INTO shops(id,name,address,raw_json,source,first_seen_at,last_seen_at,fetched_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        ("S2", "店", "東京", "{}", "hotpepper", now, now, now),
    )
    conn.commit()
    data = {
        "place_id": "PX", "rating": 4.0, "user_ratings_total": 10,
        "reviews": [
            {"author": "A", "rating": 5, "text": "良い", "language": "ja",
             "relative_time": "1 week ago", "publish_time": None},
            {"author": "B", "rating": 3, "text": "普通", "language": "ja",
             "relative_time": "2 weeks ago", "publish_time": None},
        ],
    }
    google_enrich.upsert(conn, "S2", data, now)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM reviews WHERE shop_id='S2'").fetchone()[0] == 2
    # 同じレビューを再投入してもUNIQUEで重複しない
    google_enrich.upsert(conn, "S2", data, now)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM reviews WHERE shop_id='S2'").fetchone()[0] == 2


def test_upsert_skips_empty_review_text():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    now = "2026-05-29T00:00:00+00:00"
    conn.execute(
        "INSERT INTO shops(id,name,address,raw_json,source,first_seen_at,last_seen_at,fetched_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        ("S3", "店", "東京", "{}", "hotpepper", now, now, now),
    )
    conn.commit()
    google_enrich.upsert(conn, "S3", {
        "place_id": "PY",
        "reviews": [{"author": "X", "rating": 4, "text": ""}],
    }, now)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM reviews WHERE shop_id='S3'").fetchone()[0] == 0
