"""score.py の複合適合スコアのテスト。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import score


def test_price_fit_in_band():
    assert score.price_fit([6000, 8000], 7500, 8800) == 1.0


def test_price_fit_unknown():
    assert score.price_fit([], 7500, 8800) == 0.3


def test_price_fit_decay():
    # 8800上限から1500円外れ → 1 - 1500/3000 = 0.5
    assert abs(score.price_fit([10300], 7500, 8800) - 0.5) < 1e-9


def test_price_fit_far_is_zero():
    assert score.price_fit([20000], 7500, 8800) == 0.0


def test_composite_perfect_kaishoku():
    j = {
        "atmosphere_calm": 100, "atmosphere_special": 100,
        "fully_private_room": 1, "mid_room_ok": 1,
        "instagram_score": 8, "kaishoku_score": 10,
    }
    s = score.composite_score(j, [8000], "kaishoku")
    assert s == 100.0


def test_composite_empty_low():
    j = {
        "atmosphere_calm": 0, "atmosphere_special": 0,
        "fully_private_room": 0, "mid_room_ok": 0,
        "instagram_score": 0, "kaishoku_score": 0,
    }
    # 価格不明(0.3)分だけ僅かに>0
    s = score.composite_score(j, [], "kaishoku")
    assert 0 < s < 10


def test_composite_private_unknown_partial_credit():
    base = {"atmosphere_calm": 0, "atmosphere_special": 0,
            "mid_room_ok": 0, "instagram_score": 0, "kaishoku_score": 0}
    s_none = score.composite_score({**base, "fully_private_room": None}, [8000], "kaishoku")
    s_no = score.composite_score({**base, "fully_private_room": 0}, [8000], "kaishoku")
    assert s_none > s_no  # 不明は0.4の部分点


def test_composite_accepts_dict_keys():
    # sqlite3.Row 互換の _get が dict で動くこと
    j = {"atmosphere_calm": 80, "atmosphere_special": 60}
    s = score.composite_score(j, [6000], "date")
    assert 0 < s <= 100


def test_price_target_override():
    j = {"atmosphere_calm": 0, "atmosphere_special": 0, "fully_private_room": 0,
         "mid_room_ok": 0, "instagram_score": 0, "kaishoku_score": 0}
    # 既定(7500-8800)では3000は外れだが、上書きで帯内に
    s_default = score.composite_score(j, [3000], "kaishoku")
    s_override = score.composite_score(j, [3000], "kaishoku", price_target=(2500, 3500))
    assert s_override > s_default
