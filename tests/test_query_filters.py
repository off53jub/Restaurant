"""query.py の新フィルタ (B + D の一部) のテスト。"""
import sys
import tempfile
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as dbmod
from query import query


def _seed(conn, sid, name, addr="東京", source="hotpepper"):
    now = "2026-06-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO shops(id,name,address,raw_json,source,first_seen_at,last_seen_at,fetched_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (sid, name, addr, "{}", source, now, now, now))
    conn.execute("INSERT INTO judgements(shop_id,enriched_at) VALUES(?,?)", (sid, now))
    conn.commit()


def _visit(conn, sid, days_ago=0, companions=None):
    visited_at = (dt.date.today() - dt.timedelta(days=days_ago)).isoformat()
    conn.execute(
        "INSERT INTO visits(shop_id, visited_at, companions, created_at, updated_at) "
        "VALUES(?,?,?,?,?)",
        (sid, visited_at, companions, "now", "now"))
    conn.commit()


def test_not_visited_since_excludes_recent():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    _seed(conn, "S1", "最近行った店")
    _seed(conn, "S2", "ずっと前に行った店")
    _seed(conn, "S3", "未訪問店")
    _visit(conn, "S1", days_ago=5)
    _visit(conn, "S2", days_ago=120)
    rows, _ = query(conn, not_visited_since_days=60)
    names = {r["name"] for r in rows}
    assert "最近行った店" not in names
    assert "ずっと前に行った店" in names
    assert "未訪問店" in names


def test_not_with_companion_excludes_overlapping_people():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    _seed(conn, "S1", "上司Aと行った店")
    _seed(conn, "S2", "彼女と行った店")
    _seed(conn, "S3", "誰とも行ってない")
    _visit(conn, "S1", companions="上司A 他2名")
    _visit(conn, "S2", companions="彼女")
    rows, _ = query(conn, not_with_companion="上司A")
    names = {r["name"] for r in rows}
    assert "上司Aと行った店" not in names
    assert "彼女と行った店" in names
    assert "誰とも行ってない" in names


def test_combined_filters_compose():
    """両フィルタはANDで効く（どちらかでも該当すれば除外）。"""
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    _seed(conn, "S1", "上司Aと最近")
    _seed(conn, "S2", "上司Bと最近")
    _seed(conn, "S3", "上司Aと昔")
    _seed(conn, "S4", "上司Bと昔")
    _visit(conn, "S1", days_ago=10, companions="上司A")
    _visit(conn, "S2", days_ago=10, companions="上司B")
    _visit(conn, "S3", days_ago=200, companions="上司A")
    _visit(conn, "S4", days_ago=200, companions="上司B")
    rows, _ = query(conn, not_visited_since_days=30, not_with_companion="上司A")
    names = {r["name"] for r in rows}
    # S1,S2: 最近 → 除外。S3: 上司A → 除外。S4: 両方OK → 残る
    assert names == {"上司Bと昔"}
