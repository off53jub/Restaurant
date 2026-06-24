"""ingest_gnavi.py のテスト。API呼び出しは行わず、UPSERTロジックのみ検証。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as dbmod
import ingest_gnavi
import enrich_db


SAMPLE_GNAVI = {
    "id": "g123456",
    "name": "ぐる店舗テスト",
    "name_kana": "グルテンポテスト",
    "address": "東京都中央区銀座1-1-1",
    "latitude": "35.6717",
    "longitude": "139.7639",
    "category": "和食",
    "url": "https://r.gnavi.co.jp/test/",
    "access": {"line": "JR", "station": "東京駅", "walk": "5分"},
    "budget": 8000,
    "pr": {"pr_short": "落ち着いた個室あり"},
}


def test_normalize_prefixes_id():
    out = ingest_gnavi.normalize_shop(SAMPLE_GNAVI)
    assert out["id"] == "g:g123456"
    assert out["source"] == "gnavi"
    assert out["name"] == "ぐる店舗テスト"
    assert out["lat"] == 35.6717 and out["lng"] == 139.7639
    assert out["genre_name"] == "和食"
    assert "東京駅" in out["access"]


def test_normalize_handles_missing_fields():
    out = ingest_gnavi.normalize_shop({"id": "x1", "name": "薄い店"})
    assert out["id"] == "g:x1"
    assert out["lat"] is None and out["lng"] is None
    assert out["genre_name"] == "" and out["access"] == ""


def test_upsert_inserts_with_source_and_stub_judgement():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    now = "2026-05-29T00:00:00+00:00"
    r = ingest_gnavi.upsert_shop(conn, SAMPLE_GNAVI, now)
    conn.commit()
    assert r == 1
    s = conn.execute("SELECT * FROM shops WHERE id=?", ("g:g123456",)).fetchone()
    assert s["source"] == "gnavi"
    assert s["first_seen_at"] == now and s["fetched_at"] == now
    # スタブ judgement が入る（クエリで JOIN しても落ちないように）
    j = conn.execute("SELECT * FROM judgements WHERE shop_id=?", ("g:g123456",)).fetchone()
    assert j is not None and j["kaishoku_score"] == 0


def test_upsert_returns_unchanged_when_same_payload():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    ingest_gnavi.upsert_shop(conn, SAMPLE_GNAVI, "2026-05-29T00:00:00+00:00")
    conn.commit()
    r2 = ingest_gnavi.upsert_shop(conn, SAMPLE_GNAVI, "2026-06-01T00:00:00+00:00")
    conn.commit()
    assert r2 == 3
    s = conn.execute("SELECT * FROM shops WHERE id='g:g123456'").fetchone()
    assert s["last_seen_at"] == "2026-06-01T00:00:00+00:00"
    # raw_jsonが変わってないので fetched_at は据え置き
    assert s["fetched_at"] == "2026-05-29T00:00:00+00:00"


def test_upsert_returns_updated_when_payload_changes():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    ingest_gnavi.upsert_shop(conn, SAMPLE_GNAVI, "2026-05-29T00:00:00+00:00")
    conn.commit()
    changed = dict(SAMPLE_GNAVI)
    changed["budget"] = 9000  # 変更
    r = ingest_gnavi.upsert_shop(conn, changed, "2026-06-01T00:00:00+00:00")
    conn.commit()
    assert r == 2
    s = conn.execute("SELECT * FROM shops WHERE id='g:g123456'").fetchone()
    assert s["fetched_at"] == "2026-06-01T00:00:00+00:00"


def test_enrich_db_skips_gnavi_shops():
    """ぐるなび店は HotPepper 用の enrich.judge_shop を走らせない。"""
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    # HotPepper店 1件 + ぐるなび店 1件
    now = "2026-05-29T00:00:00+00:00"
    conn.execute(
        "INSERT INTO shops(id,name,address,raw_json,source,first_seen_at,last_seen_at,fetched_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        ("J999001", "HP店", "東京", "{}", "hotpepper", now, now, now),
    )
    ingest_gnavi.upsert_shop(conn, SAMPLE_GNAVI, now)
    conn.commit()
    targets = enrich_db.select_targets(conn, max_age_days=30, limit=0)
    ids = [r["id"] for r in targets]
    assert "J999001" in ids
    assert "g:g123456" not in ids
