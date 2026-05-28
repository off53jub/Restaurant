#!/usr/bin/env python3
"""DBに対してプリセットまたはアドホック条件でクエリし、結果を整形出力。

例:
  python query.py --preset kaishoku
  python query.py --preset date_shinjuku --limit 10
  python query.py --fts "新宿 個室" --price-min 5000 --price-max 8000
  python query.py --list-presets
"""
import argparse
import json
import sys

import db as dbmod
from filter import PRESETS


def bar(v, width=10):
    if v is None:
        return "データなし"
    return "█" * (v // 10) + "░" * (width - v // 10)


def build_where(preset, area_kw=None, fts=None, price_min=None, price_max=None,
                smoking=None, fully_private=None, mid_room=None, calm_min=None,
                special_min=None, ig_min=None):
    """プリセットまたは個別引数から WHERE 句と引数を構築。"""
    where = []
    args = []
    # エリアキーワード（住所のいずれかに一致）
    keywords = area_kw or (preset.get("area_keywords") if preset else None)
    if keywords:
        ors = " OR ".join("s.address LIKE ?" for _ in keywords)
        where.append(f"({ors})")
        args.extend(f"%{k}%" for k in keywords)
    # 価格帯（drink_course_prices_json 内に範囲内の値が含まれるか）
    pmin = price_min if price_min is not None else (preset.get("price_min") if preset else None)
    pmax = price_max if price_max is not None else (preset.get("price_max") if preset else None)
    # SQLite で JSON 配列内の範囲チェックは json_each で
    has_price_filter = pmin is not None and pmax is not None
    # 個室
    fp = fully_private if fully_private is not None else (preset.get("require_fully_private") if preset else None)
    if fp:
        where.append("j.fully_private_room = 1")
    mr = mid_room if mid_room is not None else (preset.get("require_mid_room") if preset else None)
    if mr:
        where.append("j.mid_room_ok = 1")
    # 喫煙
    smk = smoking if smoking is not None else (preset.get("smoking") if preset else "any")
    if smk == "allowed":
        where.append("j.smoking_at_seat = 'allowed'")
    elif smk == "partial_ok":
        where.append("j.smoking_at_seat IN ('allowed','partial')")
    # 雰囲気
    cmin = calm_min if calm_min is not None else (preset.get("atmosphere_calm_min") if preset else None)
    if cmin is not None:
        where.append("COALESCE(j.atmosphere_calm,0) >= ?")
        args.append(cmin)
    smin = special_min if special_min is not None else (preset.get("atmosphere_special_min") if preset else None)
    if smin is not None:
        where.append("COALESCE(j.atmosphere_special,0) >= ?")
        args.append(smin)
    # インスタ
    igmin = ig_min if ig_min is not None else (preset.get("instagram_score_min") if preset else None)
    if igmin is not None:
        where.append("COALESCE(j.instagram_score,0) >= ?")
        args.append(igmin)
    # 取得失敗除外
    where.append("(j.fetch_error IS NULL OR j.fetch_error = '')")
    return where, args, has_price_filter, (pmin, pmax), fts


def query(conn, preset_name=None, **kwargs):
    preset = PRESETS.get(preset_name) if preset_name else None
    where, args, has_price, price_band, fts = build_where(preset, **kwargs)
    where_sql = " AND ".join(where) if where else "1=1"
    price_join = ""
    if has_price:
        pmin, pmax = price_band
        price_join = (
            " AND EXISTS (SELECT 1 FROM json_each(j.drink_course_prices_json) je "
            f"             WHERE CAST(je.value AS INTEGER) BETWEEN {int(pmin)} AND {int(pmax)})"
        )
    fts_join = ""
    if fts:
        fts_join = " JOIN shops_fts f ON f.rowid = s.rowid"
        where_sql = f"shops_fts MATCH ? AND " + where_sql
        args = [fts] + args

    sql = f"""
    SELECT s.*, j.*
    FROM shops s
    {fts_join}
    JOIN judgements j ON j.shop_id = s.id
    WHERE {where_sql} {price_join}
    """
    # ソート
    sort_mode = preset.get("sort") if preset else "atmosphere"
    if sort_mode == "atmosphere":
        sql += " ORDER BY COALESCE(j.atmosphere_calm,0) DESC, COALESCE(j.atmosphere_special,0) DESC, j.kaishoku_score DESC"
    elif sort_mode == "instagram":
        sql += " ORDER BY j.instagram_score DESC, COALESCE(j.atmosphere_special,0) DESC"
    elif sort_mode == "score":
        sql += " ORDER BY j.kaishoku_score DESC, j.drink_course_min_yen ASC"
    else:
        sql += " ORDER BY j.drink_course_min_yen ASC"
    return list(conn.execute(sql, args)), (preset, price_band if has_price else None)


def format_row(idx, r, price_band=None):
    drink_prices = json.loads(r["drink_course_prices_json"] or "[]")
    kaishoku_hits = json.loads(r["kaishoku_hits_json"] or "[]")
    ig_hits = json.loads(r["instagram_hits_json"] or "[]")
    band_str = ""
    if price_band:
        pmin, pmax = price_band
        in_band = [p for p in drink_prices if pmin <= p <= pmax]
        band_str = " / ".join(f"{p:,}円" for p in in_band)
    all_str = " / ".join(f"{p:,}円" for p in drink_prices[:6])
    smoke_label = {
        "allowed": "○ 喫煙可", "partial": "△ 分煙",
        "unknown": "? 記載なし", "forbidden": "× 全面禁煙",
    }.get(r["smoking_at_seat"], "?")
    parts = [
        f"\n【{idx}】 {r['name']}  [会食スコア{r['kaishoku_score']}]",
        f"   ジャンル : {r['genre_name']}",
        f"   住所     : {r['address']}",
        f"   アクセス : {r['access']}",
        f"   雰囲気   : 落ち着いた {bar(r['atmosphere_calm'])} "
        f"{r['atmosphere_calm'] if r['atmosphere_calm'] is not None else '?'}/100",
        f"             特別な日   {bar(r['atmosphere_special'])} "
        f"{r['atmosphere_special'] if r['atmosphere_special'] is not None else '?'}/100",
    ]
    if band_str:
        parts.append(f"   ★該当帯  : {band_str}")
    parts.extend([
        f"   全コース : {all_str}",
        f"   個室     : 完全個室{'○' if r['fully_private_room'] else '?'}"
        f" / 5-8名個室{'○' if r['mid_room_ok'] else '?'}"
        f" {('['+r['mid_room_evidence']+']') if r['mid_room_evidence'] else ''}",
        f"   喫煙     : {smoke_label}",
        f"   インスタ : スコア{r['instagram_score']} [{', '.join(ig_hits[:6])}]",
        f"   会食適性 : {', '.join(kaishoku_hits[:6])}",
        f"   URL      : {r['pc_url']}",
    ])
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser(description="DBクエリ")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--preset", choices=list(PRESETS.keys()))
    ap.add_argument("--list-presets", action="store_true")
    ap.add_argument("--fts", help="名前・住所・アクセスを全文検索（例: '新宿 個室'）")
    ap.add_argument("--area", action="append", help="エリアキーワード（複数可、addressにLIKE一致）")
    ap.add_argument("--price-min", type=int)
    ap.add_argument("--price-max", type=int)
    ap.add_argument("--smoking", choices=["any", "allowed", "partial_ok"])
    ap.add_argument("--fully-private", action="store_true")
    ap.add_argument("--mid-room", action="store_true")
    ap.add_argument("--calm-min", type=int)
    ap.add_argument("--special-min", type=int)
    ap.add_argument("--ig-min", type=int)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if args.list_presets:
        for k, v in PRESETS.items():
            print(f"  {k}: {v['description']}")
        return

    conn = dbmod.connect(args.db)
    rows, (preset, price_band) = query(
        conn,
        preset_name=args.preset,
        area_kw=args.area,
        fts=args.fts,
        price_min=args.price_min,
        price_max=args.price_max,
        smoking=args.smoking,
        fully_private=args.fully_private or None,
        mid_room=args.mid_room or None,
        calm_min=args.calm_min,
        special_min=args.special_min,
        ig_min=args.ig_min,
    )
    total = len(rows)
    if args.limit > 0:
        rows = rows[: args.limit]

    if preset:
        print(f"# プリセット: {args.preset} — {preset['description']}")
    else:
        print(f"# アドホッククエリ")
    if args.limit > 0 and total > len(rows):
        print(f"# 該当: {total}件（上位{len(rows)}件を表示）\n")
    else:
        print(f"# 該当: {total}件\n")
    print("=" * 80)
    for i, r in enumerate(rows, 1):
        print(format_row(i, r, price_band))


if __name__ == "__main__":
    main()
