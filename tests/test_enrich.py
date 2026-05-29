"""enrich.py の抽出ロジックの退行防止テスト。

実行: .venv/bin/python -m pytest -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import enrich


# ---- 飲み放題コース価格 ----

def test_drink_course_basic():
    assert enrich.extract_drink_course_prices("飲み放題付きコース 4,000円") == [4000]


def test_drink_course_excludes_single_drink_below_floor():
    # 単品ドリンク価格(550円)は floor 2500 未満で除外
    assert enrich.extract_drink_course_prices("生ビール 飲み放題 550円") == []


def test_drink_course_excludes_addon_prefix():
    # 「+3,000円」は追加料金とみなし除外、コース3,000円のみ採用
    text = "宴会コース 3,000円。飲み放題は +3,000円 別途"
    assert enrich.extract_drink_course_prices(text) == [3000]


def test_drink_course_window_excludes_far_price():
    # 飲み放題から200字超離れた価格は窓外で除外
    text = "飲み放題" + ("あ" * 250) + "9,999円"
    assert enrich.extract_drink_course_prices(text) == []


def test_drink_course_min_yen_param():
    # min_yen を下げれば安価コースも拾える
    assert enrich.extract_drink_course_prices("飲み放題コース 1,500円", min_yen=1000) == [1500]


# ---- 通常コース価格 ----

def test_course_any_basic():
    out = enrich.extract_course_prices_any("ディナーコース 5,000円 / コース 8,000円")
    assert 5000 in out and 8000 in out


# ---- 完全個室 ----

def test_fully_private_true():
    ok, ev = enrich.detect_fully_private("完全個室あり、接待に最適")
    assert ok is True and ev == "完全個室"


def test_fully_private_semi_is_false():
    ok, _ = enrich.detect_fully_private("半個室のご用意があります")
    assert ok is False


def test_fully_private_unknown():
    ok, _ = enrich.detect_fully_private("個室あり")
    assert ok is None


# ---- 5-8名個室 ----

def test_mid_room_max8():
    ok, _ = enrich.detect_mid_room("最大8名の個室")
    assert ok is True


def test_mid_room_6mei_made():
    ok, _ = enrich.detect_mid_room("個室は6名様まで")
    assert ok is True


def test_mid_room_no_match():
    ok, _ = enrich.detect_mid_room("カウンター席のみ")
    assert ok is None


# ---- 会食適性スコア ----

def test_kaishoku_score():
    score, hits = enrich.detect_kaishoku("接待や会食に最適、落ち着いた空間")
    assert score == 3
    assert set(hits) == {"接待", "会食", "落ち着いた"}


# ---- インスタ映え ----

def test_instagram_score():
    score, hits = enrich.detect_instagram("夜景がきれいでインスタ映え、テラス席あり")
    assert score == 3
    assert "夜景" in hits and "インスタ映え" in hits and "テラス" in hits


# ---- 喫煙 ----

def test_smoking_forbidden():
    assert enrich.detect_smoking("全席禁煙です")[0] == "forbidden"


def test_smoking_allowed():
    assert enrich.detect_smoking("喫煙可の席あり")[0] == "allowed"


def test_smoking_partial():
    assert enrich.detect_smoking("分煙です")[0] == "partial"


def test_smoking_priority_allowed_over_forbidden():
    # 「喫煙可」が先に評価される（優先度: 可 > 禁煙）
    assert enrich.detect_smoking("喫煙可。一部禁煙席もあり")[0] == "allowed"


# ---- 雰囲気スライダー ----

ATMOSPHERE_HTML = """
<dl class="atmosphereWrap">
  <dt>お店の雰囲気</dt>
  <dd><span>にぎやか</span>
      <input class="range" type="range" min="0" max="100" value="80" disabled>
      <span>落ち着いた</span></dd>
  <dd><span>普段使い</span>
      <input class="range" type="range" min="0" max="100" value="60" disabled>
      <span>特別な日</span></dd>
</dl>
"""


def test_atmosphere_extract():
    calm, special = enrich.extract_atmosphere(ATMOSPHERE_HTML)
    assert calm == 80 and special == 60


def test_atmosphere_missing():
    assert enrich.extract_atmosphere("<html><body>なし</body></html>") == (None, None)


def test_atmosphere_error_html():
    assert enrich.extract_atmosphere("__ERROR__: Timeout") == (None, None)


# ---- fetch リトライ ----

def test_fetch_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    class Resp:
        text = "<html>ok</html>"
        def raise_for_status(self):
            pass

    def flaky_get(url, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("boom")
        return Resp()

    monkeypatch.setattr(enrich.requests, "get", flaky_get)
    monkeypatch.setattr(enrich.time, "sleep", lambda *_: None)  # バックオフ短縮
    out = enrich.fetch("http://x", retries=2, backoff=0)
    assert out == "<html>ok</html>"
    assert calls["n"] == 3


def test_fetch_all_fail_returns_error(monkeypatch):
    def always_fail(url, **kw):
        raise TimeoutError("nope")

    monkeypatch.setattr(enrich.requests, "get", always_fail)
    monkeypatch.setattr(enrich.time, "sleep", lambda *_: None)
    out = enrich.fetch("http://x", retries=1, backoff=0)
    assert out.startswith("__ERROR__") and "TimeoutError" in out
