"""nijikai.py のテスト。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as dbmod
import nijikai


def test_haversine_zero():
    assert nijikai.haversine_m(35.67, 139.75, 35.67, 139.75) == 0


def test_haversine_tokyo_short_distance():
    # 緯度差0.001(=約111m) → 110m前後
    d = nijikai.haversine_m(35.670, 139.75, 35.671, 139.75)
    assert 100 < d < 120


def test_haversine_known_pair():
    # 東京駅(35.6812,139.7671)〜銀座駅(35.6717,139.7639) は約1.1km
    d = nijikai.haversine_m(35.6812, 139.7671, 35.6717, 139.7639)
    assert 1000 < d < 1200


def _seed(conn, sid, name, lat, lng, genre, calm=None):
    now = "2026-05-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO shops(id,name,address,lat,lng,genre_name,pc_url,raw_json,"
        "first_seen_at,last_seen_at,fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (sid, name, "test addr", lat, lng, genre,
         f"https://x/{sid}", "{}", now, now, now),
    )
    conn.execute(
        "INSERT INTO judgements(shop_id,kaishoku_score,instagram_score,"
        "atmosphere_calm,fetch_error,enriched_at) VALUES (?,?,?,?,?,?)",
        (sid, 0, 0, calm, None, now),
    )
    conn.commit()


def test_find_nijikai_within_distance():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    # 中心: 35.67, 139.75
    _seed(conn, "S1", "近い良いバー", 35.6702, 139.7503, "バー・カクテル", calm=80)
    _seed(conn, "S2", "遠いバー",     35.6820, 139.7600, "バー・カクテル", calm=90)
    _seed(conn, "S3", "近い焼肉",     35.6701, 139.7501, "焼肉・ホルモン",  calm=60)
    cands = nijikai.find_nijikai(conn, 35.6700, 139.7500, max_distance_m=600)
    ids = [r["id"] for _, r in cands]
    assert "S1" in ids and "S3" not in ids  # ジャンルフィルタ
    assert "S2" not in ids                   # 距離フィルタ


def test_find_nijikai_excludes_source_shop():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    _seed(conn, "ME", "自分", 35.67, 139.75, "バー・カクテル", calm=80)
    _seed(conn, "OTHER", "他", 35.6705, 139.7505, "バー・カクテル", calm=70)
    cands = nijikai.find_nijikai(conn, 35.67, 139.75, exclude_shop_id="ME")
    assert all(r["id"] != "ME" for _, r in cands)


def test_find_nijikai_sorts_by_calm_then_distance():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    _seed(conn, "A", "落ち着き高い少し遠い", 35.6705, 139.7510, "バー・カクテル", calm=90)
    _seed(conn, "B", "落ち着き低い近い",     35.6701, 139.7501, "バー・カクテル", calm=30)
    cands = nijikai.find_nijikai(conn, 35.67, 139.75)
    # 落ち着き優先 → A が先
    assert cands[0][1]["id"] == "A"


def test_find_nijikai_no_latlng_returns_empty():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    assert nijikai.find_nijikai(conn, None, 139.75) == []
