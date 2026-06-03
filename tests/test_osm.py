"""ingest_osm.py のテスト。Overpass API呼び出しはせず、パーサー/UPSERTのみ。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as dbmod
import ingest_osm
import enrich_db


NODE_FULL = {
    "type": "node", "id": 123456789,
    "lat": 35.67, "lon": 139.75,
    "tags": {
        "amenity": "restaurant",
        "name": "テスト和食店",
        "name:ja_kana": "テストワショクテン",
        "cuisine": "japanese;sushi",
        "addr:province": "東京都", "addr:city": "港区",
        "addr:street": "虎ノ門1-1-1",
        "website": "https://example.com/sushi",
        "description": "落ち着いた個室あり",
    }
}

WAY_WITH_CENTER = {
    "type": "way", "id": 987654321,
    "center": {"lat": 35.6896, "lon": 139.7006},
    "tags": {"amenity": "cafe", "name": "新宿カフェ"}
}

ELEMENT_MISSING_NAME_AND_GEO = {
    "type": "node", "id": 1, "tags": {"amenity": "bar"}  # 座標なし
}


def test_normalize_node():
    out = ingest_osm.normalize_shop(NODE_FULL)
    assert out["id"] == "osm:node/123456789"
    assert out["source"] == "osm"
    assert out["name"] == "テスト和食店"
    assert out["genre_name"] == "和食"   # cuisine=japanese で和食に
    assert out["lat"] == 35.67 and out["lng"] == 139.75
    assert "港区" in out["address"]
    assert out["pc_url"] == "https://example.com/sushi"


def test_normalize_way_uses_center():
    out = ingest_osm.normalize_shop(WAY_WITH_CENTER)
    assert out["id"] == "osm:way/987654321"
    assert out["lat"] == 35.6896 and out["lng"] == 139.7006
    assert out["genre_name"] == "カフェ・スイーツ"


def test_normalize_falls_back_to_amenity_genre():
    el = {"type": "node", "id": 10, "lat": 35.0, "lon": 139.0,
          "tags": {"amenity": "pub", "name": "居酒屋A"}}
    assert ingest_osm.normalize_shop(el)["genre_name"] == "居酒屋"


def test_normalize_unknown_name_defaults():
    el = {"type": "node", "id": 11, "lat": 35.0, "lon": 139.0,
          "tags": {"amenity": "bar"}}
    assert ingest_osm.normalize_shop(el)["name"] == "(名前未登録)"


def test_url_fallback_to_osm_link():
    el = {"type": "node", "id": 42, "lat": 35.0, "lon": 139.0,
          "tags": {"amenity": "cafe", "name": "C"}}
    out = ingest_osm.normalize_shop(el)
    assert out["pc_url"] == "https://www.openstreetmap.org/node/42"


def test_upsert_inserts_with_source_osm_and_stub_judgement():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    now = "2026-05-29T00:00:00+00:00"
    r = ingest_osm.upsert_shop(conn, NODE_FULL, now)
    conn.commit()
    assert r == 1
    s = conn.execute("SELECT * FROM shops WHERE id='osm:node/123456789'").fetchone()
    assert s["source"] == "osm" and s["name"] == "テスト和食店"
    j = conn.execute("SELECT * FROM judgements WHERE shop_id='osm:node/123456789'").fetchone()
    assert j is not None and j["kaishoku_score"] == 0


def test_upsert_skips_elements_without_coords():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    r = ingest_osm.upsert_shop(conn, ELEMENT_MISSING_NAME_AND_GEO, "2026-05-29T00:00:00+00:00")
    assert r == 0
    assert conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0] == 0


def test_upsert_unchanged_payload_returns_3():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    ingest_osm.upsert_shop(conn, NODE_FULL, "2026-05-29T00:00:00+00:00")
    conn.commit()
    r = ingest_osm.upsert_shop(conn, NODE_FULL, "2026-06-15T00:00:00+00:00")
    conn.commit()
    assert r == 3
    s = conn.execute("SELECT * FROM shops WHERE id='osm:node/123456789'").fetchone()
    assert s["last_seen_at"] == "2026-06-15T00:00:00+00:00"
    assert s["fetched_at"] == "2026-05-29T00:00:00+00:00"


def test_enrich_db_skips_osm_shops():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    now = "2026-05-29T00:00:00+00:00"
    conn.execute(
        "INSERT INTO shops(id,name,address,raw_json,source,first_seen_at,last_seen_at,fetched_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        ("J999777", "HP店", "東京", "{}", "hotpepper", now, now, now),
    )
    ingest_osm.upsert_shop(conn, NODE_FULL, now)
    conn.commit()
    ids = [r["id"] for r in enrich_db.select_targets(conn, 30, 0)]
    assert "J999777" in ids
    assert "osm:node/123456789" not in ids
