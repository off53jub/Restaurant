"""H1 Wayback / H2 opening_hours のテスト。外部fetchは行わない。"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as dbmod
import enrich_opening
import enrich_wayback


# ---- H2 opening_hours ----

def test_hp_parse_dinner_only():
    txt = "月～金、祝前日: 17:30～21:30 （料理L.O. 21:00 ドリンクL.O. 21:00）"
    o = enrich_opening.parse_hp_open(txt)
    assert o["has_dinner"] is True
    assert o["has_lunch"] is False
    assert o["dinner_lo_hour"] == 21
    assert o["dinner_only"] is True


def test_hp_parse_late_night_yokujitsu():
    txt = "月～金: 17:00～翌2:00 （料理L.O. 翌1:00 ドリンクL.O. 翌1:00）"
    o = enrich_opening.parse_hp_open(txt)
    assert o["late_night"] is True
    assert o["dinner_lo_hour"] == 25  # 翌1時→25扱い


def test_hp_parse_lunch_and_dinner():
    txt = "月～金: 11:30～14:30 17:30～23:00 （料理L.O. 22:30）"
    o = enrich_opening.parse_hp_open(txt)
    assert o["has_lunch"] is True
    assert o["has_dinner"] is True
    assert o["dinner_only"] is False
    assert o["dinner_lo_hour"] == 22


def test_hp_parse_late_via_close_time():
    txt = "月～土: 18:00～23:30"
    o = enrich_opening.parse_hp_open(txt)
    assert o["late_night"] is True


def test_osm_parse_simple():
    o = enrich_opening.parse_osm_opening("Mo-Su 17:00-23:00")
    assert o["has_lunch"] is False
    assert o["has_dinner"] is True
    assert o["late_night"] is True


def test_osm_parse_lunch_dinner():
    o = enrich_opening.parse_osm_opening("Mo-Fr 11:00-14:30,17:00-22:00")
    assert o["has_lunch"] is True
    assert o["has_dinner"] is True


def test_osm_parse_empty_returns_raw():
    o = enrich_opening.parse_osm_opening("24/7")
    # 数値抽出できないなら raw を返す（仕様: 構造化失敗時もinfo残す）
    assert o.get("raw") == "24/7"


def test_extract_dispatches_by_source():
    raw_hp = '{"open":"月～金: 17:00～23:00"}'
    raw_osm = '{"tags":{"opening_hours":"Mo-Su 17:00-23:00"}}'
    h = enrich_opening.extract(raw_hp, "hotpepper")
    o = enrich_opening.extract(raw_osm, "osm")
    assert h["source"] == "hotpepper" and h["has_dinner"]
    assert o["source"] == "osm" and o["has_dinner"]


def test_extract_handles_bad_json():
    assert enrich_opening.extract("not-json", "hotpepper") is None


# ---- H1 Wayback ----

def test_wayback_fetch_history_aggregates(monkeypatch):
    """各年のsnapshotを集約し first/last/count を返すこと。"""
    calls = []
    fake = {
        2010: {"available": True, "timestamp": "20100315120000"},
        2018: {"available": True, "timestamp": "20180720000000"},
        2024: {"available": True, "timestamp": "20240105000000"},
    }
    def fake_check(url, year, timeout=10):
        calls.append(year)
        return fake.get(year)
    monkeypatch.setattr(enrich_wayback, "check_year", fake_check)
    monkeypatch.setattr(enrich_wayback.time, "sleep", lambda *_: None)
    h = enrich_wayback.fetch_history("http://x")
    assert h["first_year"] == 2010
    assert h["last_year"] == 2024
    assert h["snapshot_count"] == 3
    # 全PROBE_YEARSを試している
    assert len(calls) == len(enrich_wayback.PROBE_YEARS)


def test_wayback_fetch_history_no_snapshots(monkeypatch):
    monkeypatch.setattr(enrich_wayback, "check_year", lambda u, y, timeout=10: None)
    monkeypatch.setattr(enrich_wayback.time, "sleep", lambda *_: None)
    h = enrich_wayback.fetch_history("http://x")
    assert h["first_year"] is None
    assert h["last_year"] is None
    assert h["snapshot_count"] == 0


def test_wayback_check_year_returns_none_when_unavailable(monkeypatch):
    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"archived_snapshots": {}}
    monkeypatch.setattr(enrich_wayback.requests, "get",
                        lambda *a, **kw: Resp())
    assert enrich_wayback.check_year("http://x", 2020) is None
