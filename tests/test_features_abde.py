"""A/B/D/E（ダッシュボード・比較・リコメンド・Google拡張）のテスト。"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as dbmod
import visit
import recommend
import compare
import google_enrich


def _seed_shop(conn, sid, name="店", addr="東京都港区赤坂1-1", genre="居酒屋",
               calm=70, special=40, prices_json="[5000,8000]"):
    now = "2026-05-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO shops(id,name,address,lat,lng,genre_name,pc_url,raw_json,"
        "first_seen_at,last_seen_at,fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (sid, name, addr, 35.67, 139.74, genre, f"https://x/{sid}",
         "{}", now, now, now),
    )
    conn.execute(
        "INSERT INTO judgements(shop_id,kaishoku_score,instagram_score,"
        "atmosphere_calm,atmosphere_special,drink_course_prices_json,"
        "fetch_error,enriched_at) VALUES (?,?,?,?,?,?,?,?)",
        (sid, 0, 0, calm, special, prices_json, None, now),
    )
    conn.commit()


def _seed_visit(conn, shop_id=None, **fields):
    args = argparse.Namespace(
        shop_id=shop_id, search=None, manual=bool(not shop_id), name=fields.get("name", "manual"),
        address=fields.get("address", "京都市"), url=None,
        date=fields.get("date", "2026-05-20"), rating=fields.get("rating"),
        cost=fields.get("cost"), scene=fields.get("scene"),
        companions=None, course=None,
        private_room=None, would_revisit=fields.get("would_revisit"),
        notes=None, tags=fields.get("tags"),
    )
    visit.cmd_add(conn, args)


# ---- A: ダッシュボード ----

def test_stats_empty_db():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    visit.cmd_stats(conn, argparse.Namespace(format="text"))  # 例外出なければOK


def test_stats_json_payload(capsys):
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    _seed_shop(conn, "S1", genre="和食")
    _seed_visit(conn, shop_id="S1", rating=5, cost=8000, scene="kaishoku",
                tags="個室,日本酒", date="2026-03-15", would_revisit=1)
    _seed_visit(conn, shop_id="S1", rating=4, cost=10000, scene="kaishoku",
                date="2026-05-01", would_revisit=1)
    capsys.readouterr()  # seedの "追加 id=..." を捨てる
    visit.cmd_stats(conn, argparse.Namespace(format="json"))
    out = json.loads(capsys.readouterr().out)
    assert out["total"] == 2
    assert out["average_rating"] == 4.5
    assert out["would_revisit_rate"] == 1.0
    assert any(g["genre"] == "和食" for g in out["by_genre_top10"])
    # リピート店
    assert out["repeated_shops"] and out["repeated_shops"][0]["visits"] == 2
    # 平均コスト
    sc = {x["scene"]: x for x in out["avg_cost_by_scene"]}
    assert sc["kaishoku"]["avg_yen"] == 9000


# ---- B: 比較 ----

def test_compare_renders_table():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    _seed_shop(conn, "S1", name="花びし", calm=80)
    _seed_shop(conn, "S2", name="パセラ", calm=90)
    rows = compare.fetch_shops_by_ids(conn, ["S1", "S2"])
    html = compare.render(rows, scene="kaishoku", price_band=(7500, 8800),
                          conn=conn, nijikai_opts=None)
    assert "<table>" in html and "花びし" in html and "パセラ" in html
    assert "適合度(kaishoku)" in html


def test_compare_fetch_invalid_id_raises():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    try:
        compare.fetch_shops_by_ids(conn, ["NOPE"])
        assert False
    except SystemExit:
        pass


# ---- D: リコメンド ----

def test_build_profile_returns_none_when_no_visits():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    assert recommend.build_profile(conn, min_rating=4) is None


def test_build_profile_aggregates_visits():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    _seed_shop(conn, "S1", genre="和食", addr="東京都港区虎ノ門1", calm=80)
    _seed_shop(conn, "S2", genre="和食", addr="東京都港区赤坂2", calm=70)
    _seed_visit(conn, shop_id="S1", rating=5, cost=9000)
    _seed_visit(conn, shop_id="S2", rating=4, cost=7000)
    p = recommend.build_profile(conn, min_rating=4)
    assert p["sample_size"] == 2
    assert p["genre_pref"]["和食"] == 2
    assert p["ward_pref"]["港区"] == 2
    assert 70 <= p["calm_mean"] <= 80
    assert p["cost_mean"] == 8000


def test_build_profile_captures_review_scene_avg():
    """好きな店のHotPepper口コミシーン平均が profile に入る。"""
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    _seed_shop(conn, "S1", genre="和食")
    _seed_shop(conn, "S2", genre="和食")
    # 接待実績の指標を入れる
    conn.execute(
        "UPDATE judgements SET hotpepper_review_scenes='{\"kaishoku\":80}' WHERE shop_id='S1'")
    conn.execute(
        "UPDATE judgements SET hotpepper_review_scenes='{\"kaishoku\":40}' WHERE shop_id='S2'")
    _seed_visit(conn, shop_id="S1", rating=5)
    _seed_visit(conn, shop_id="S2", rating=5)
    conn.commit()
    p = recommend.build_profile(conn, min_rating=4)
    assert p["review_scene_avg"]["kaishoku"] == 60  # (80+40)/2


def test_recommend_excludes_visited_and_returns_top():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    _seed_shop(conn, "S1", name="行った", genre="和食", calm=80)
    _seed_shop(conn, "S2", name="未訪問A", genre="和食", calm=78)
    _seed_shop(conn, "S3", name="未訪問B", genre="焼肉", calm=80)
    _seed_visit(conn, shop_id="S1", rating=5, cost=8000)
    profile = recommend.build_profile(conn, 4)
    recs = recommend.recommend(conn, profile, limit=5)
    names = [r["name"] for _, r in recs]
    assert "行った" not in names      # 訪問済み除外
    assert "未訪問A" in names         # ジャンル一致で残る
    # ジャンル絞り込み（top3）により焼肉は和食1件のみなら漏れる可能性。
    # ここでは「未訪問Aが含まれる」ことのみ確認


# ---- E: Google ----

def test_price_level_mapping():
    assert google_enrich._price_level_to_int("PRICE_LEVEL_INEXPENSIVE") == 1
    assert google_enrich._price_level_to_int("PRICE_LEVEL_VERY_EXPENSIVE") == 4
    assert google_enrich._price_level_to_int(None) is None


def test_google_upsert_and_replay():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    _seed_shop(conn, "S1")
    data = {"place_id": "PID1", "rating": 4.3, "user_ratings_total": 120,
            "price_level": 3, "business_status": "OPERATIONAL",
            "types_json": "[]"}
    google_enrich.upsert(conn, "S1", data, "2026-05-29T00:00:00+00:00")
    conn.commit()
    r = conn.execute("SELECT * FROM google WHERE shop_id='S1'").fetchone()
    assert r["rating"] == 4.3 and r["user_ratings_total"] == 120
    # 上書き
    google_enrich.upsert(conn, "S1", {"error": "no match"},
                         "2026-06-01T00:00:00+00:00")
    conn.commit()
    r2 = conn.execute("SELECT * FROM google WHERE shop_id='S1'").fetchone()
    assert r2["fetch_error"] == "no match"


def test_google_filter_in_query():
    """--google-min がクエリに効くこと。"""
    from query import query as query_fn
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    _seed_shop(conn, "S1", name="高評価")
    _seed_shop(conn, "S2", name="低評価")
    google_enrich.upsert(conn, "S1", {"rating": 4.5, "user_ratings_total": 200,
                                       "place_id": "P1"}, "2026-05-01T00:00:00+00:00")
    google_enrich.upsert(conn, "S2", {"rating": 3.0, "user_ratings_total": 5,
                                       "place_id": "P2"}, "2026-05-01T00:00:00+00:00")
    conn.commit()
    rows, _ = query_fn(conn, google_min=4.0)
    names = [r["name"] for r in rows]
    assert "高評価" in names and "低評価" not in names
