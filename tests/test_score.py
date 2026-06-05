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
    """全成分パーフェクト（接待実績含む）で100点満点。"""
    j = {
        "atmosphere_calm": 100, "atmosphere_special": 100,
        "fully_private_room": 1, "mid_room_ok": 1,
        "instagram_score": 8, "kaishoku_score": 10,
        "hotpepper_review_scenes": '{"kaishoku":30}',
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


def test_kaishoku_actual_lifts_score():
    """口コミシーン接待件数があると kaishoku 適合度が大きく上がる。"""
    base = {"atmosphere_calm": 70, "atmosphere_special": 50,
            "fully_private_room": 1, "mid_room_ok": 1,
            "instagram_score": 0, "kaishoku_score": 5,
            "hotpepper_review_scenes": None}
    s_no = score.composite_score(base, [8000], "kaishoku")
    base_with = dict(base, hotpepper_review_scenes='{"kaishoku":90}')
    s_yes = score.composite_score(base_with, [8000], "kaishoku")
    assert s_yes > s_no
    # 90件は飽和（30件で1.0）
    base_30 = dict(base, hotpepper_review_scenes='{"kaishoku":30}')
    assert score.composite_score(base_30, [8000], "kaishoku") == s_yes


def test_date_actual_uses_date_count_only():
    """date シーンは kaishoku_actual ではなく date 件数を見る。"""
    j_kaishoku_only = {"atmosphere_calm": 80, "atmosphere_special": 70,
                       "fully_private_room": 0, "instagram_score": 3,
                       "kaishoku_score": 0,
                       "hotpepper_review_scenes": '{"kaishoku":50,"date":0}'}
    j_date_only = dict(j_kaishoku_only,
                       hotpepper_review_scenes='{"kaishoku":0,"date":50}')
    s_k = score.composite_score(j_kaishoku_only, [6000], "date")
    s_d = score.composite_score(j_date_only, [6000], "date")
    assert s_d > s_k


def test_actual_handles_bad_json():
    j = {"atmosphere_calm": 50, "atmosphere_special": 30,
         "fully_private_room": 1, "mid_room_ok": 1,
         "instagram_score": 0, "kaishoku_score": 0,
         "hotpepper_review_scenes": "not-json"}
    # 例外で落ちず、actual 成分が 0 扱いになる
    s = score.composite_score(j, [8000], "kaishoku")
    assert 0 < s < 100


def test_price_target_override():
    j = {"atmosphere_calm": 0, "atmosphere_special": 0, "fully_private_room": 0,
         "mid_room_ok": 0, "instagram_score": 0, "kaishoku_score": 0}
    # 既定(7500-8800)では3000は外れだが、上書きで帯内に
    s_default = score.composite_score(j, [3000], "kaishoku")
    s_override = score.composite_score(j, [3000], "kaishoku", price_target=(2500, 3500))
    assert s_override > s_default
