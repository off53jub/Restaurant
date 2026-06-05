"""G1〜G8 のテスト。外部APIは呼ばず、パース/upsertロジックのみ。"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as dbmod
import enrich_amenities
import enrich_jsonld
import enrich_corporation
import enrich_foursquare
import ingest_tokyo_opendata


# ---- G4 amenities ----

def test_g4_osm_yes_no_normalization():
    raw = '{"tags": {"wheelchair":"yes","takeaway":"no","outdoor_seating":"yes",' \
          '"payment:credit_cards":"yes","drink:sake":"local","level":"3"}}'
    a = enrich_amenities.extract_osm_amenities(raw)
    assert a["wheelchair"] is True
    assert a["takeaway"] is False
    assert a["outdoor_seating"] is True
    assert a["payment:credit_cards"] is True
    assert a["drink:sake"] == "local"
    assert a["level"] == "3"


def test_g4_hotpepper_yesno_mapping():
    raw = '{"private_room":"あり","non_smoking":"全面禁煙","card":"なし","barrier_free":"あり"}'
    a = enrich_amenities.extract_hotpepper_amenities(raw)
    assert a["private_room"] is True
    # 「全面禁煙」も True 扱い（禁煙ルールあり→non_smoking=true）
    assert a["non_smoking"] is True
    assert a["payment:credit_cards"] is False
    assert a["wheelchair"] is True


def test_g4_hotpepper_credit_card_variants():
    """HotPepperの多様な表記をクレカ可として判定。"""
    for v in ["利用可", "主要カード（VISA、JCB等）", "VISA、Master可"]:
        raw = '{"card":"' + v + '"}'
        a = enrich_amenities.extract_hotpepper_amenities(raw)
        assert a["payment:credit_cards"] is True, f"failed for {v}"


def test_g4_empty_for_bad_json():
    assert enrich_amenities.extract_osm_amenities("not-json") == {}
    assert enrich_amenities.extract_hotpepper_amenities(None) == {}


# ---- G5 JSON-LD ----

def test_g5_extracts_restaurant_ldjson():
    html = """<html><head>
    <script type="application/ld+json">
    {"@type":"Restaurant","name":"テスト店","priceRange":"¥¥",
     "telephone":"03-0000-0000","openingHours":"Mo-Su 17:00-23:00"}
    </script></head><body></body></html>"""
    out = enrich_jsonld.extract_jsonld(html)
    assert out["@type"] == "Restaurant"
    assert out["priceRange"] == "¥¥"


def test_g5_prefers_richest_among_multiple():
    html = """<html><body>
    <script type="application/ld+json">{"@type":"LocalBusiness","name":"A"}</script>
    <script type="application/ld+json">
    {"@type":"Restaurant","name":"B","openingHours":"Mo-Su 17-23",
     "menu":"https://x/menu","priceRange":"¥¥¥"}</script>
    </body></html>"""
    out = enrich_jsonld.extract_jsonld(html)
    assert out["name"] == "B"


def test_g5_returns_none_when_no_restaurant_type():
    html = '<script type="application/ld+json">{"@type":"Article","name":"X"}</script>'
    assert enrich_jsonld.extract_jsonld(html) is None


def test_g5_handles_graph_array():
    html = """<script type="application/ld+json">
    {"@graph":[{"@type":"WebSite","name":"site"},
               {"@type":"Restaurant","name":"店","servesCuisine":"Japanese"}]}
    </script>"""
    out = enrich_jsonld.extract_jsonld(html)
    assert out["servesCuisine"] == "Japanese"


# ---- G2 法人番号 ----

def test_g2_pick_best_prefers_name_match():
    cands = [
        {"name": "全然違う会社", "prefectureName": "東京都"},
        {"name": "テスト商事株式会社", "prefectureName": "東京都"},
    ]
    picked = enrich_corporation.pick_best("テスト商事", "東京都港区", cands)
    assert picked["name"] == "テスト商事株式会社"


def test_g2_pick_best_error_passthrough():
    cands = [{"error": "boom"}]
    assert enrich_corporation.pick_best("X", "Y", cands) == {"error": "boom"}


def test_g2_pick_best_empty():
    assert enrich_corporation.pick_best("X", "Y", []) is None


# ---- G1 Foursquare ----

def test_g1_search_uses_radius_and_query(monkeypatch):
    captured = {}
    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"results": [{"fsq_id": "ABC123", "name": "店"}]}
    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return Resp()
    monkeypatch.setattr(enrich_foursquare.requests, "get", fake_get)
    out = enrich_foursquare.search_place("KEY", "店", 35.67, 139.75)
    assert out["fsq_id"] == "ABC123"
    assert captured["params"]["ll"] == "35.67,139.75"
    assert captured["params"]["query"] == "店"
    assert captured["headers"]["Authorization"] == "KEY"


# ---- G6 Tokyo Open Data ----

def test_g6_find_col_with_aliases():
    assert ingest_tokyo_opendata.find_col(["名称", "住所"], ["名称", "店舗名"]) == "名称"
    assert ingest_tokyo_opendata.find_col(["施設名", "X"], ["店舗名", "施設名"]) == "施設名"
    assert ingest_tokyo_opendata.find_col(["X"], ["名称"]) is None


def test_g6_end_to_end_csv_ingest():
    import csv as csvmod
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    csvfile = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w",
                                          encoding="utf-8-sig", newline="")
    w = csvmod.writer(csvfile)
    w.writerow(["名称", "所在地", "緯度", "経度"])
    w.writerow(["都内店", "東京都港区赤坂1", "35.67", "139.74"])
    w.writerow(["都外店", "神奈川県横浜市西区1", "35.45", "139.62"])
    csvfile.close()

    import sys as _sys
    old = _sys.argv
    _sys.argv = ["ingest_tokyo_opendata.py", "--db", db, "--csv", csvfile.name,
                 "--dataset-name", "test"]
    try:
        ingest_tokyo_opendata.main()
    finally:
        _sys.argv = old

    conn = dbmod.connect(db)
    names = [r["name"] for r in conn.execute("SELECT name FROM shops WHERE source='tokyo'")]
    assert "都内店" in names
    assert "都外店" not in names
