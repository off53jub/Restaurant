"""シーン別の複合適合スコア（0-100）。

キーワード出現数だけに頼らず、HotPepper自身の雰囲気スライダー（操作されにくい）・
価格適合・個室有無などを加重平均して算出する。
"""
from typing import Optional


# 各シーンの重み（合計1.0）と価格ターゲット帯
SCENE_PROFILES = {
    "kaishoku": {
        "weights": {
            "calm": 0.28, "special": 0.14, "price_fit": 0.18,
            "private": 0.22, "mid_room": 0.10, "kaishoku": 0.08,
        },
        "price_target": (7500, 8800),
    },
    "date": {
        "weights": {
            "calm": 0.30, "special": 0.30, "price_fit": 0.15,
            "private": 0.10, "instagram": 0.15,
        },
        "price_target": (5000, 8000),
    },
    "instagram": {
        "weights": {
            "instagram": 0.45, "special": 0.28, "calm": 0.12, "price_fit": 0.15,
        },
        "price_target": (5000, 8000),
    },
}


def price_fit(prices, lo, hi):
    """価格帯適合度 0-1。帯内に1つでもあれば1.0、外れは距離で減衰、不明は0.3。"""
    if not prices:
        return 0.3
    if any(lo <= p <= hi for p in prices):
        return 1.0
    nearest = min(prices, key=lambda p: min(abs(p - lo), abs(p - hi)))
    d = min(abs(nearest - lo), abs(nearest - hi))
    return max(0.0, 1.0 - d / 3000.0)  # 3000円外れで0


def _get(j, key):
    """dict と sqlite3.Row の両方からキー取得（無ければ None）。"""
    try:
        return j[key]
    except (KeyError, IndexError):
        return None


def _component(name, j, prices, target):
    if name == "calm":
        return (_get(j, "atmosphere_calm") or 0) / 100.0
    if name == "special":
        return (_get(j, "atmosphere_special") or 0) / 100.0
    if name == "private":
        v = _get(j, "fully_private_room")
        return 1.0 if v == 1 or v is True else (0.4 if v is None else 0.0)
    if name == "mid_room":
        v = _get(j, "mid_room_ok")
        return 1.0 if v == 1 or v is True else 0.0
    if name == "instagram":
        return min((_get(j, "instagram_score") or 0) / 8.0, 1.0)
    if name == "kaishoku":
        return min((_get(j, "kaishoku_score") or 0) / 10.0, 1.0)
    if name == "price_fit":
        return price_fit(prices, *target)
    return 0.0


def composite_score(j, prices, scene, price_target: Optional[tuple] = None):
    """シーン適合度 0-100 を返す。

    j: judgement相当のdict/Row（atmosphere_calm等のキーを持つ）
    prices: drink_course_prices のリスト
    scene: SCENE_PROFILES のキー
    price_target: 明示指定があればプロファイルの既定を上書き
    """
    profile = SCENE_PROFILES[scene]
    target = price_target or profile["price_target"]
    weights = profile["weights"]
    total = sum(weights.values())
    s = sum(w * _component(name, j, prices, target) for name, w in weights.items())
    return round(100.0 * s / total, 1)
