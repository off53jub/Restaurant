#!/usr/bin/env python3
"""enriched.json に対して名前付きプリセットでフィルタ＋ソートして出力する。

新しいシーン（デート/家族/接待 等）は PRESETS にエントリ追加するだけで再利用可。
"""
import argparse
import json
import sys
from pathlib import Path

CORE_TORANOMON = [
    "虎ノ門", "新橋", "赤坂", "銀座", "六本木", "汐留", "霞が関",
    "内幸町", "浜松町", "西新橋", "麻布", "新富", "築地", "愛宕",
]
CORE_SHINJUKU = [
    "新宿", "西新宿", "歌舞伎町", "代々木", "千駄ヶ谷", "信濃町",
    "四谷", "四ツ谷", "曙橋", "市ヶ谷", "中野坂上",
]


# プリセット定義: 1か所追加すればいつでも再現できる
PRESETS = {
    # 役員会食: 完全個室・5-8名・喫煙可・7500-8800円・落ち着いた雰囲気
    "kaishoku": {
        "description": "役員会食（虎ノ門3km / 完全個室 / 5-8名 / 喫煙可 / 7,500-8,800円コース）",
        "area_keywords": CORE_TORANOMON,
        "require_fully_private": True,
        "require_mid_room": True,        # 5-8名個室の明記
        "smoking": "allowed",            # "allowed" / "partial_ok" / "any"
        "price_min": 7500,               # 飲み放題込みコース価格帯
        "price_max": 8800,
        "atmosphere_calm_min": None,     # フィルタには使わない（ソートのみ）
        "atmosphere_special_min": None,
        "sort": "atmosphere",            # "atmosphere" / "score" / "price"
    },
    # インスタ映えデート（新宿圏）— フォトジェニック重視
    "instagram_shinjuku": {
        "description": "新宿3km / インスタ映えデート / 5,000-8,000円 / 半個室OK",
        "area_keywords": CORE_SHINJUKU,
        "require_fully_private": False,
        "require_mid_room": False,
        "smoking": "any",
        "price_min": 5000,
        "price_max": 8000,
        "atmosphere_calm_min": None,
        "atmosphere_special_min": None,
        "instagram_score_min": 6,
        "sort": "instagram",
    },
    # デート（新宿圏）— 落ち着いた大人デート / 5,000-8,000円 / 半個室OK
    "date_shinjuku": {
        "description": "新宿3km / 落ち着いた大人デート / 5,000-8,000円 / 半個室OK",
        "area_keywords": CORE_SHINJUKU,
        "require_fully_private": False,
        "require_mid_room": False,
        "smoking": "any",
        "price_min": 5000,
        "price_max": 8000,
        "atmosphere_calm_min": 50,
        "atmosphere_special_min": 30,
        "sort": "atmosphere",
    },
}


def matches(j, s, preset):
    if j.get("fetch_error"):
        return False, None
    if preset["require_fully_private"] and j.get("fully_private_room") is not True:
        return False, None
    if preset["require_mid_room"] and j.get("mid_room_ok") is not True:
        return False, None
    smk = j.get("smoking_at_seat")
    if preset["smoking"] == "allowed" and smk != "allowed":
        return False, None
    if preset["smoking"] == "partial_ok" and smk not in ("allowed", "partial"):
        return False, None
    area = next((k for k in preset["area_keywords"] if k in s.get("address", "")), None)
    if not area:
        return False, None
    prices = j.get("drink_course_prices") or []
    band = [p for p in prices if preset["price_min"] <= p <= preset["price_max"]]
    if not band:
        return False, None
    if preset.get("atmosphere_calm_min") is not None:
        if (j.get("atmosphere_calm") or 0) < preset["atmosphere_calm_min"]:
            return False, None
    if preset.get("atmosphere_special_min") is not None:
        if (j.get("atmosphere_special") or 0) < preset["atmosphere_special_min"]:
            return False, None
    if preset.get("instagram_score_min") is not None:
        if (j.get("instagram_score") or 0) < preset["instagram_score_min"]:
            return False, None
    return True, (area, band)


def sort_key(item, mode):
    s, j, area, band = item
    if mode == "atmosphere":
        return (-(j.get("atmosphere_calm") or 0),
                -(j.get("atmosphere_special") or 0),
                -j.get("kaishoku_score", 0),
                min(band))
    if mode == "score":
        return (-j.get("kaishoku_score", 0), min(band))
    if mode == "instagram":
        return (-(j.get("instagram_score") or 0),
                -(j.get("atmosphere_special") or 0),
                min(band))
    return (min(band),)


def bar(v, width=10):
    if v is None:
        return "データなし"
    return "█" * (v // 10) + "░" * (width - v // 10)


def format_shop(idx, s, j, area, band):
    calm = j.get("atmosphere_calm")
    spec = j.get("atmosphere_special")
    band_str = " / ".join(f"{p:,}円" for p in band)
    all_str = " / ".join(f"{p:,}円" for p in (j.get("drink_course_prices") or [])[:6])
    smoke_label = {
        "allowed": "○ 喫煙可", "partial": "△ 分煙",
        "unknown": "? 記載なし", "forbidden": "× 全面禁煙",
    }.get(j.get("smoking_at_seat"), "?")
    return "\n".join([
        f"\n【{idx}】 {s.get('name','')}  [会食スコア{j.get('kaishoku_score',0)}]",
        f"   ジャンル : {s.get('genre',{}).get('name','')}",
        f"   エリア   : {area} / {s.get('address','')}",
        f"   アクセス : {s.get('access','')}",
        f"   雰囲気   : 落ち着いた {bar(calm)} {calm if calm is not None else '?'}/100",
        f"             特別な日   {bar(spec)} {spec if spec is not None else '?'}/100",
        f"   ★該当帯  : {band_str}",
        f"   全コース : {all_str}",
        f"   個室     : 完全個室{'○' if j.get('fully_private_room') else '?'}"
        f" / 5-8名個室{'○' if j.get('mid_room_ok') else '?'}"
        f" {('['+j.get('mid_room_evidence','')+']') if j.get('mid_room_evidence') else ''}",
        f"   喫煙     : {smoke_label}",
        f"   インスタ  : スコア{j.get('instagram_score',0)} [{', '.join(j.get('instagram_hits',[])[:6])}]",
        f"   会食適性 : {', '.join(j.get('kaishoku_hits',[])[:6])}",
        f"   URL      : {s.get('urls',{}).get('pc','')}",
    ])


def main():
    ap = argparse.ArgumentParser(description="enriched.json をプリセット条件でフィルタ")
    ap.add_argument("--input", default="output/enriched.json")
    ap.add_argument("--preset", choices=list(PRESETS.keys()), required=True)
    ap.add_argument("--limit", type=int, default=0, help=">0で上位N件のみ")
    ap.add_argument("--list-presets", action="store_true")
    args = ap.parse_args()

    if args.list_presets:
        for name, p in PRESETS.items():
            print(f"{name}: {p['description']}")
        return

    preset = PRESETS[args.preset]
    data = json.loads(Path(args.input).read_text())

    matched = []
    for e in data:
        ok, meta = matches(e["judgement"], e["shop"], preset)
        if ok:
            area, band = meta
            matched.append((e["shop"], e["judgement"], area, band))

    matched.sort(key=lambda x: sort_key(x, preset["sort"]))
    if args.limit > 0:
        matched = matched[: args.limit]

    print(f"# プリセット: {args.preset}")
    print(f"# {preset['description']}")
    print(f"# 該当: {len(matched)}件\n")
    print("=" * 80)
    for i, (s, j, area, band) in enumerate(matched, 1):
        print(format_shop(i, s, j, area, band))


if __name__ == "__main__":
    main()
