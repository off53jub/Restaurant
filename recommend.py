#!/usr/bin/env python3
"""訪問記録の★高評価店から特徴を抽出し、似た未訪問店をリコメンド。

抽出する特徴:
  - 好きなジャンル分布（visited∩DB の genre_name 頻度）
  - 好きなエリア分布（住所の区別）
  - 雰囲気の選好（calm/special の平均、価格レンジ平均）
  - シーン別に分けても計算可能

スコア = ジャンル一致度 + エリア一致度 + 雰囲気近さ + 価格近さ
未訪問の店を上位N件返す。
"""
import argparse
import json
import re
from collections import Counter

import db as dbmod
from query import format_row


WARD_RE = re.compile(
    r"(千代田区|中央区|港区|新宿区|文京区|台東区|墨田区|江東区|品川区|目黒区|"
    r"大田区|世田谷区|渋谷区|中野区|杉並区|豊島区|北区|荒川区|板橋区|練馬区|"
    r"足立区|葛飾区|江戸川区)"
)


def build_profile(conn, min_rating=4, scene=None):
    """好み(★min_rating+)のプロファイルを返す。"""
    where = "v.rating >= ? AND v.shop_id IS NOT NULL"
    params = [min_rating]
    if scene:
        where += " AND v.scene = ?"
        params.append(scene)
    rows = list(conn.execute(
        f"SELECT s.genre_name, s.address, j.atmosphere_calm, j.atmosphere_special, "
        f"       j.drink_course_prices_json, v.cost_per_person "
        f"FROM visits v "
        f"JOIN shops s ON s.id = v.shop_id "
        f"JOIN judgements j ON j.shop_id = s.id "
        f"WHERE {where}",
        params,
    ))
    if not rows:
        return None

    genre_counts = Counter(r["genre_name"] for r in rows if r["genre_name"])
    ward_counts = Counter()
    for r in rows:
        m = WARD_RE.search(r["address"] or "")
        if m:
            ward_counts[m.group(1)] += 1

    calms = [r["atmosphere_calm"] for r in rows if r["atmosphere_calm"] is not None]
    specs = [r["atmosphere_special"] for r in rows if r["atmosphere_special"] is not None]
    costs = [r["cost_per_person"] for r in rows if r["cost_per_person"]]

    return {
        "sample_size": len(rows),
        "genre_pref": dict(genre_counts),       # 'g': N
        "ward_pref": dict(ward_counts),
        "calm_mean": (sum(calms) / len(calms)) if calms else None,
        "special_mean": (sum(specs) / len(specs)) if specs else None,
        "cost_mean": (sum(costs) / len(costs)) if costs else None,
    }


def score_shop(shop_row, judg_row, profile):
    """0-1の正規化スコア。値が無い因子はスキップして平均する。"""
    n_total = sum(profile["genre_pref"].values())
    n_wards = sum(profile["ward_pref"].values()) or 1
    parts = []

    # ジャンル
    g = shop_row["genre_name"]
    if n_total and g:
        parts.append(profile["genre_pref"].get(g, 0) / n_total)

    # エリア
    addr = shop_row["address"] or ""
    m = WARD_RE.search(addr)
    if m and profile["ward_pref"]:
        parts.append(profile["ward_pref"].get(m.group(1), 0) / n_wards)

    # 雰囲気: 平均からの近さ（差0で1, 100で0）
    for key, mean in (("atmosphere_calm", profile["calm_mean"]),
                      ("atmosphere_special", profile["special_mean"])):
        v = judg_row[key]
        if v is not None and mean is not None:
            parts.append(max(0.0, 1.0 - abs(v - mean) / 100.0))

    # 価格: 平均コストからの近さ（差0で1、5000円以上離れたら0）
    if profile["cost_mean"]:
        prices = json.loads(judg_row["drink_course_prices_json"] or "[]")
        if prices:
            nearest = min(prices, key=lambda p: abs(p - profile["cost_mean"]))
            parts.append(max(0.0, 1.0 - abs(nearest - profile["cost_mean"]) / 5000.0))

    if not parts:
        return 0.0
    return sum(parts) / len(parts)


def explain(shop_row, judg_row, profile):
    """なぜ似ているかの短い説明。"""
    bits = []
    g = shop_row["genre_name"]
    if g and profile["genre_pref"].get(g):
        bits.append(f"{g}({profile['genre_pref'][g]}回)")
    m = WARD_RE.search(shop_row["address"] or "")
    if m and profile["ward_pref"].get(m.group(1)):
        bits.append(f"{m.group(1)}({profile['ward_pref'][m.group(1)]}回)")
    if profile["calm_mean"] is not None and judg_row["atmosphere_calm"] is not None:
        if abs(judg_row["atmosphere_calm"] - profile["calm_mean"]) < 15:
            bits.append(f"落ち着き感が好み平均({int(profile['calm_mean'])})に近い")
    if profile["cost_mean"]:
        prices = json.loads(judg_row["drink_course_prices_json"] or "[]")
        if prices and min(abs(p - profile["cost_mean"]) for p in prices) < 2000:
            bits.append(f"価格帯が好み平均({int(profile['cost_mean']):,}円)に近い")
    return " / ".join(bits) if bits else "特徴一致少"


def recommend(conn, profile, limit=10, area_kw=None, scene=None):
    """未訪問のenrich済み店からスコア順に返す。"""
    where = [
        "NOT EXISTS (SELECT 1 FROM visits v WHERE v.shop_id = s.id)",
        "(j.fetch_error IS NULL OR j.fetch_error = '')",
    ]
    params = []
    if area_kw:
        ors = " OR ".join("s.address LIKE ?" for _ in area_kw)
        where.append(f"({ors})")
        params.extend(f"%{k}%" for k in area_kw)
    # 好きなジャンル上位3に絞ってショートリスト
    top_genres = sorted(profile["genre_pref"].items(), key=lambda x: -x[1])[:3]
    if top_genres:
        ph = ",".join("?" * len(top_genres))
        where.append(f"s.genre_name IN ({ph})")
        params.extend(g for g, _ in top_genres)
    sql = f"""
    SELECT s.*, j.*
    FROM shops s JOIN judgements j ON j.shop_id = s.id
    WHERE {' AND '.join(where)}
    """
    rows = list(conn.execute(sql, params))
    scored = [(score_shop(r, r, profile), r) for r in rows]
    scored.sort(key=lambda x: -x[0])
    return scored[:limit]


def main():
    ap = argparse.ArgumentParser(description="訪問履歴から似た未訪問店をリコメンド")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--min-rating", type=int, default=4,
                    help="この★以上の訪問記録を「好み」とする(既定4)")
    ap.add_argument("--scene", help="このシーンの好みだけ抽出(kaishoku/date/...)")
    ap.add_argument("--area", action="append", help="絞り込み(複数可)")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    conn = dbmod.connect(args.db)
    profile = build_profile(conn, args.min_rating, args.scene)
    if not profile:
        raise SystemExit(
            f"★{args.min_rating}+ かつ shop_id付きの訪問記録がありません。"
            f"\nまず `visit add` で記録を増やすか --min-rating を下げてください。"
        )
    recs = recommend(conn, profile, args.limit, args.area, args.scene)

    if args.format == "json":
        print(json.dumps({
            "profile": profile,
            "recommendations": [
                {"score": round(s, 3), "name": r["name"], "address": r["address"],
                 "genre": r["genre_name"], "url": r["pc_url"]}
                for s, r in recs
            ],
        }, ensure_ascii=False, indent=2))
        return

    print(f"# あなたの好みプロファイル（★{args.min_rating}+ / n={profile['sample_size']})")
    if profile["genre_pref"]:
        print(f"  好きなジャンル: " + ", ".join(
            f"{g}({n})" for g, n in sorted(profile['genre_pref'].items(), key=lambda x: -x[1])
        ))
    if profile["ward_pref"]:
        print(f"  よく行くエリア: " + ", ".join(
            f"{w}({n})" for w, n in sorted(profile['ward_pref'].items(), key=lambda x: -x[1])
        ))
    if profile["calm_mean"] is not None:
        print(f"  落ち着き感の好み平均: {int(profile['calm_mean'])}/100")
    if profile["cost_mean"]:
        print(f"  価格帯の好み平均: 約{int(profile['cost_mean']):,}円")
    print(f"\n# おすすめ未訪問店 {len(recs)}件\n" + "=" * 70)
    for i, (s, r) in enumerate(recs, 1):
        print(f"\n【{i}】 {r['name']}  類似度{s*100:.0f}%")
        print(f"   ジャンル: {r['genre_name']} / 住所: {r['address']}")
        print(f"   理由: {explain(r, r, profile)}")
        print(f"   URL: {r['pc_url']}")


if __name__ == "__main__":
    main()
