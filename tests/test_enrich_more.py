"""HotPepperページからの shop_description 抽出と Wikidata 連携のテスト。"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as dbmod
import enrich
import enrich_wiki


HOTPEPPER_HTML = """<html><body>
<div class="column5A">店先には、和の趣を感じさせる暖簾を掲げ、落ち着いた雰囲気でお客様をお迎えいたします。お食事前から期待感を高める佇まいは、普段使いはもちろん、大切な方とのお食事にもぴったりです。</div>
<div class="column5A">周りを気にせずゆったりとお過ごしいただける完全個室を完備しております。接待や会食、記念日、ご家族でのお食事など、落ち着いた空間で大切な時間を過ごしたいシーンにおすすめです。</div>
<div class="column5A">短い文</div>
<div class="column5A">店先には、和の趣を感じさせる暖簾を掲げ、落ち着いた雰囲気でお客様をお迎えいたします。お食事前から期待感を高める佇まいは、普段使いはもちろん、大切な方とのお食事にもぴったりです。</div>
</body></html>"""


def test_extract_shop_description_picks_text_blocks():
    out = enrich.extract_shop_description(HOTPEPPER_HTML)
    assert "和の趣" in out
    assert "完全個室" in out
    # 短すぎる「短い文」は除外
    assert "短い文" not in out
    # 同文の重複は1回だけ
    assert out.count("和の趣を感じさせる暖簾") == 1


def test_extract_shop_description_empty_on_error():
    assert enrich.extract_shop_description("__ERROR__: timeout") == ""
    assert enrich.extract_shop_description("") == ""


def test_extract_shop_description_excludes_menu_blocks():
    """「○○円（税込）」付きブロックは即除外。料金3個以上ブロックも除外。"""
    html = """<html><body>
    <div class="column5A">看板料理の鴨ロースは上質なお肉と皮下脂肪が絶妙な逸品。 1,650円（税込）</div>
    <div class="column5A">完全個室を完備しており、接待や会食、記念日に最適な落ち着いた空間でゆったりとお過ごしいただけます。</div>
    <div class="column5A">焼鳥盛り合わせ 900円 / 季節野菜の天ぷら 750円 / 鴨ロース 1,650円</div>
    </body></html>"""
    out = enrich.extract_shop_description(html)
    assert "完全個室" in out
    assert "鴨ロース" not in out
    assert "1,650円" not in out


def test_extract_shop_description_allows_casual_price_mention():
    """店紹介内の「コースは3,000円から」のような単発価格言及は通す。"""
    html = '''<div class="column5A">本格的なコース料理を3,000円からご用意。接待や会食にお使いください。</div>'''
    out = enrich.extract_shop_description(html)
    assert "接待や会食" in out


def test_extract_shop_description_truncates_to_max():
    big = "<html><body>" + "".join(
        f'<div class="column5A">{"あ"*200}_{i}_</div>'
        for i in range(10)
    ) + "</body></html>"
    out = enrich.extract_shop_description(big, max_chars=300)
    assert len(out) <= 300


# ---- enrich_wiki ----

def test_search_wikidata_filters_non_restaurant():
    """飲食店っぽくないヒットは弾かれることを確認。"""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "search": [
            {"id": "Q1", "label": "あいうえお", "description": "anime character"},
            {"id": "Q2", "label": "あいうえお", "description": "restaurant in Tokyo"},
        ]
    }
    mock_response.raise_for_status = lambda: None
    with patch("enrich_wiki.requests.get", return_value=mock_response):
        out = enrich_wiki.search_wikidata("あいうえお")
        assert out["wikidata_id"] == "Q2"


def test_search_wikidata_returns_none_when_no_match():
    mock_response = MagicMock()
    mock_response.json.return_value = {"search": []}
    mock_response.raise_for_status = lambda: None
    with patch("enrich_wiki.requests.get", return_value=mock_response):
        assert enrich_wiki.search_wikidata("nonexistent shop name") is None


def test_upsert_writes_wiki_row():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    now = "2026-05-29T00:00:00+00:00"
    conn.execute(
        "INSERT INTO shops(id,name,address,raw_json,source,first_seen_at,last_seen_at,fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("W1", "老舗料亭", "東京", "{}", "hotpepper", now, now, now),
    )
    conn.commit()
    enrich_wiki.upsert(conn, "W1", {
        "wikidata_id": "Q999",
        "label": "老舗料亭",
        "description": "Japanese restaurant in Tokyo",
        "wikipedia_ja_url": "https://ja.wikipedia.org/wiki/老舗料亭",
        "summary": "明治創業の老舗。",
    }, now)
    conn.commit()
    r = conn.execute("SELECT * FROM wiki WHERE shop_id='W1'").fetchone()
    assert r["wikidata_id"] == "Q999"
    assert r["summary"] == "明治創業の老舗。"


def test_migrate_adds_shop_description_column():
    """init_db → migrate で judgements.shop_description が必ず存在する。"""
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = dbmod.init_db(db)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(judgements)").fetchall()]
    assert "shop_description" in cols
    # 再 init_db は冪等
    conn2 = dbmod.init_db(db)
    cols2 = [r["name"] for r in conn2.execute("PRAGMA table_info(judgements)").fetchall()]
    assert "shop_description" in cols2
