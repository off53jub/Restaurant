"""visit.py の主要動作テスト。一時DBで完結。"""
import sys
from pathlib import Path
import tempfile
import argparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as dbmod
import visit


def tmp_db():
    return tempfile.NamedTemporaryFile(suffix=".db", delete=False).name


def seed_shop(conn, shop_id="J999001", name="テスト店", address="東京都港区虎ノ門1-1-1"):
    now = "2026-05-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO shops(id,name,address,raw_json,first_seen_at,last_seen_at,fetched_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (shop_id, name, address, "{}", now, now, now),
    )
    conn.commit()


def make_args(**kw):
    """argparse.Namespaceをdictから作るヘルパ。"""
    return argparse.Namespace(**kw)


def base_add_args(**overrides):
    base = dict(
        shop_id=None, search=None, manual=False, name=None, address=None, url=None,
        date="2026-05-20", rating=None, cost=None, scene=None, companions=None,
        course=None, private_room=None, would_revisit=None, notes=None, tags=None,
    )
    base.update(overrides)
    return make_args(**base)


def test_add_with_shop_id():
    db = tmp_db()
    conn = dbmod.init_db(db)
    seed_shop(conn)
    args = base_add_args(shop_id="J999001", rating=5, cost=8800,
                         scene="kaishoku", notes="個室良し")
    visit.cmd_add(conn, args)
    r = conn.execute("SELECT * FROM visits").fetchone()
    assert r["shop_id"] == "J999001"
    assert r["rating"] == 5 and r["cost_per_person"] == 8800
    assert r["scene"] == "kaishoku" and r["notes"] == "個室良し"
    assert r["visited_at"] == "2026-05-20"


def test_add_manual():
    db = tmp_db()
    conn = dbmod.init_db(db)
    args = base_add_args(manual=True, name="未在", address="京都市東山区",
                         rating=5, cost=30000)
    visit.cmd_add(conn, args)
    r = conn.execute("SELECT * FROM visits").fetchone()
    assert r["shop_id"] is None
    assert r["manual_name"] == "未在"
    assert r["manual_address"] == "京都市東山区"


def test_add_rejects_invalid_shop_id():
    db = tmp_db()
    conn = dbmod.init_db(db)
    args = base_add_args(shop_id="NOPE")
    try:
        visit.cmd_add(conn, args)
        assert False, "should raise"
    except SystemExit:
        pass


def test_add_requires_name_for_manual():
    db = tmp_db()
    conn = dbmod.init_db(db)
    args = base_add_args(manual=True)  # nameなし
    try:
        visit.cmd_add(conn, args)
        assert False
    except SystemExit:
        pass


def test_edit_updates_fields():
    db = tmp_db()
    conn = dbmod.init_db(db)
    seed_shop(conn)
    visit.cmd_add(conn, base_add_args(shop_id="J999001", rating=3))
    vid = conn.execute("SELECT id FROM visits").fetchone()["id"]
    eargs = make_args(
        id=vid, date=None, rating=5, cost=10000, scene=None,
        companions=None, course=None, private_room=None,
        would_revisit=1, notes="再評価", tags=None,
    )
    visit.cmd_edit(conn, eargs)
    r = conn.execute("SELECT * FROM visits WHERE id=?", (vid,)).fetchone()
    assert r["rating"] == 5 and r["cost_per_person"] == 10000
    assert r["would_revisit"] == 1 and r["notes"] == "再評価"


def test_rm_deletes():
    db = tmp_db()
    conn = dbmod.init_db(db)
    seed_shop(conn)
    visit.cmd_add(conn, base_add_args(shop_id="J999001"))
    vid = conn.execute("SELECT id FROM visits").fetchone()["id"]
    visit.cmd_rm(conn, make_args(id=vid))
    assert conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 0


def test_normalize_date_variants():
    assert visit.normalize_date("2026-05-29") == "2026-05-29"
    assert visit.normalize_date("20260529") == "2026-05-29"
    # 'today' は本日を返す（その値そのものは依存するので形だけ確認）
    assert len(visit.normalize_date("today")) == 10


def test_normalize_date_invalid():
    try:
        visit.normalize_date("yesterday")
        assert False
    except SystemExit:
        pass


def test_visit_to_dict_db_join():
    db = tmp_db()
    conn = dbmod.init_db(db)
    seed_shop(conn, name="花びし", address="東京都港区新橋3")
    visit.cmd_add(conn, base_add_args(shop_id="J999001", rating=4))
    row = conn.execute(
        "SELECT v.*, s.name, s.address, s.pc_url, s.genre_name "
        "FROM visits v LEFT JOIN shops s ON s.id = v.shop_id"
    ).fetchone()
    d = visit.visit_to_dict(row)
    assert d["name"] == "花びし"  # shopsの名前で上書きされる
    assert d["in_db"] is True


def test_visit_to_dict_manual():
    db = tmp_db()
    conn = dbmod.init_db(db)
    visit.cmd_add(conn, base_add_args(manual=True, name="未在", address="京都市"))
    row = conn.execute(
        "SELECT v.*, s.name, s.address, s.pc_url, s.genre_name "
        "FROM visits v LEFT JOIN shops s ON s.id = v.shop_id"
    ).fetchone()
    d = visit.visit_to_dict(row)
    assert d["name"] == "未在" and d["in_db"] is False
