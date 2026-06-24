"""H1(FOODS)/H3(YouTube)/H4(逆ジオ)/H5(HotPepper口コミ) のテスト。外部fetchはしない。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as dbmod
import enrich_geo
import enrich_youtube
import enrich_reviews_hotpepper as hpr
import ingest_foods


# ---- H4 逆ジオ ----

def test_ward_from_address():
    assert enrich_geo.ward_from_address("東京都港区赤坂1-1") == "港区"
    assert enrich_geo.ward_from_address("東京都新宿区西新宿2") == "新宿区"
    assert enrich_geo.ward_from_address("神奈川県横浜市") is None


def test_muni_cd_dict_covers_23_wards():
    assert len(enrich_geo.MUNI_CD_WARD) == 23
    assert enrich_geo.MUNI_CD_WARD["13103"] == "港区"
    assert enrich_geo.MUNI_CD_WARD["13104"] == "新宿区"


# ---- H5 HotPepper口コミ ----

REPORT_HTML = """<html><body>
<a href="/strJ001/report/">口コミ(151)</a>
<span>総合 3.8</span> <span>料理・味 4.0</span> <span>雰囲気 3.9</span>
<a href="/CSP/psi010/doReport?SP=J001&reportFilter=9">会社の宴会（58）</a>
<a href="/CSP/psi010/doReport?SP=J001&reportFilter=5">接待・会食（15）</a>
<a href="/CSP/psi010/doReport?SP=J001&reportFilter=1">デート（2）</a>
<p class="reportText">接待で利用しました。個室が落ち着いていてよかったです。料理も美味しかった。</p>
<p class="reportText">短い</p>
<p class="reportText">会社の宴会で使いました。広い個室で盛り上がれました。コスパも良いです。</p>
</body></html>"""


def test_parse_reports_total_and_scenes():
    out = hpr.parse_reports(REPORT_HTML)
    assert out["total"] == 151
    assert out["scenes"]["company"] == 58
    assert out["scenes"]["kaishoku"] == 15
    assert out["scenes"]["date"] == 2


def test_parse_reports_ratings():
    out = hpr.parse_reports(REPORT_HTML)
    assert out["ratings"]["総合"] == 3.8
    assert out["ratings"]["料理・味"] == 4.0


def test_parse_reports_review_bodies_filter_short():
    out = hpr.parse_reports(REPORT_HTML)
    # 15字未満の「短い」は除外
    assert len(out["reviews"]) == 2
    assert all(len(t) >= 15 for t in out["reviews"])


def test_parse_reports_error_html():
    out = hpr.parse_reports("__ERROR__: timeout")
    assert out["total"] is None and "error" in out


def test_hpr_save_writes_counts_and_reviews():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    now = "2026-06-04T00:00:00+00:00"
    conn.execute(
        "INSERT INTO shops(id,name,address,raw_json,source,first_seen_at,last_seen_at,fetched_at)"
        " VALUES('J1','店','東京','{}','hotpepper',?,?,?)", (now, now, now))
    conn.execute("INSERT INTO judgements(shop_id,enriched_at) VALUES('J1',?)", (now,))
    conn.commit()
    hpr.save(conn, "J1", hpr.parse_reports(REPORT_HTML), now)
    conn.commit()
    j = conn.execute("SELECT * FROM judgements WHERE shop_id='J1'").fetchone()
    assert j["hotpepper_review_count"] == 151
    import json
    assert json.loads(j["hotpepper_review_scenes"])["company"] == 58
    assert conn.execute("SELECT COUNT(*) FROM reviews WHERE shop_id='J1' AND source='hotpepper'").fetchone()[0] == 2


# ---- H3 YouTube ----

def test_youtube_relevance_filter():
    assert hpr  # ensure import
    assert enrich_youtube.is_relevant(["日本酒と和食 花びし 紹介", "別の動画"], "日本酒と和食 花びし")
    assert not enrich_youtube.is_relevant(["全然違う料理動画", "猫"], "日本酒と和食 花びし")


# ---- H1 FOODS ----

def test_foods_resolve_columns():
    header = ["業者名", "施設所在地", "業種", "許可番号", "許可年月日"]
    cols = ingest_foods.resolve_columns(header)
    assert cols["name"] == "業者名"
    assert cols["address"] == "施設所在地"
    assert cols["biz_type"] == "業種"


def test_foods_resolve_columns_alias_variants():
    header = ["名称", "所在地", "営業の種類"]
    cols = ingest_foods.resolve_columns(header)
    assert cols["name"] == "名称"
    assert cols["address"] == "所在地"
    assert cols["biz_type"] == "営業の種類"


def test_foods_normalize_extracts_fields():
    cols = {"name": "業者名", "address": "施設所在地", "biz_type": "業種",
            "permit_no": "許可番号", "permit_date": "許可年月日"}
    row = {"業者名": " 居酒屋A ", "施設所在地": "東京都港区赤坂1",
           "業種": "飲食店営業", "許可番号": "P123", "許可年月日": "2020-01-01"}
    name, address, biz, no, date = ingest_foods.normalize(row, cols)
    assert name == "居酒屋A" and address == "東京都港区赤坂1"
    assert biz == "飲食店営業" and no == "P123"


def test_foods_csv_ingest_end_to_end():
    """小さなCSVを書いて取込→23区飲食店だけ入ることを確認。"""
    import csv as csvmod
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    csv_path = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w",
                                           encoding="utf-8-sig", newline="")
    w = csvmod.writer(csv_path)
    w.writerow(["業者名", "施設所在地", "業種", "許可番号", "許可年月日"])
    w.writerow(["個人店すし", "東京都中央区銀座8-1", "飲食店営業", "P1", "2021-05-01"])
    w.writerow(["工場B", "東京都港区芝5-1", "食品製造業", "P2", "2020-01-01"])  # 非飲食→除外
    w.writerow(["横浜店", "神奈川県横浜市西区1", "飲食店営業", "P3", "2019-01-01"])  # 区外→除外
    csv_path.close()

    import argparse
    args = argparse.Namespace(db=db, csv=csv_path.name, encoding="utf-8-sig",
                              wards_only=True, limit=0)
    # main() を直接呼ぶ代わりにロジックを再現するのは冗長なのでmainを呼ぶ
    import sys as _sys
    old = _sys.argv
    _sys.argv = ["ingest_foods.py", "--db", db, "--csv", csv_path.name]
    try:
        ingest_foods.main()
    finally:
        _sys.argv = old
    conn = dbmod.connect(db)
    rows = list(conn.execute("SELECT name, address FROM shops WHERE source='foods'"))
    names = [r["name"] for r in rows]
    assert "個人店すし" in names
    assert "工場B" not in names      # 非飲食除外
    assert "横浜店" not in names      # 区外除外
    # judgements.ward が埋まっている
    w = conn.execute("SELECT ward FROM judgements j JOIN shops s ON s.id=j.shop_id "
                     "WHERE s.name='個人店すし'").fetchone()
    assert w["ward"] == "中央区"
