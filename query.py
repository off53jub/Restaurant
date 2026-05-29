#!/usr/bin/env python3
"""DBに対してプリセットまたはアドホック条件でクエリし、結果を整形出力。

例:
  python query.py --preset kaishoku
  python query.py --preset date_shinjuku --limit 10
  python query.py --fts "新宿 個室" --price-min 5000 --price-max 8000
  python query.py --list-presets
"""
import argparse
import csv
import json
import sys

import db as dbmod
from filter import PRESETS
from score import composite_score
import nijikai


def row_fit(r, scene, price_band):
    """行のシーン適合度（scene未指定なら None）。"""
    if not scene:
        return None
    prices = json.loads(r["drink_course_prices_json"] or "[]")
    return composite_score(r, prices, scene, price_band)


def row_to_dict(idx, r, price_band=None, scene=None):
    """1行を出力用のフラットな dict に変換（csv/json/tsv 共通）。"""
    drink_prices = json.loads(r["drink_course_prices_json"] or "[]")
    in_band = ""
    if price_band:
        pmin, pmax = price_band
        in_band = "/".join(str(p) for p in drink_prices if pmin <= p <= pmax)
    d = {
        "rank": idx,
        "fit_score": row_fit(r, scene, price_band),
        "name": r["name"],
        "genre": r["genre_name"],
        "address": r["address"],
        "access": r["access"],
        "drink_course_min_yen": r["drink_course_min_yen"],
        "drink_course_prices": "/".join(str(p) for p in drink_prices),
        "in_band_prices": in_band,
        "fully_private_room": r["fully_private_room"],
        "mid_room_ok": r["mid_room_ok"],
        "mid_room_evidence": r["mid_room_evidence"],
        "smoking": r["smoking_at_seat"],
        "kaishoku_score": r["kaishoku_score"],
        "atmosphere_calm": r["atmosphere_calm"],
        "atmosphere_special": r["atmosphere_special"],
        "instagram_score": r["instagram_score"],
        "url": r["pc_url"],
    }
    try:
        if r["google_rating"] is not None:
            d["google_rating"] = r["google_rating"]
            d["google_reviews"] = r["google_reviews"]
    except (IndexError, KeyError):
        pass
    if d["fit_score"] is None:
        del d["fit_score"]
    return d


def emit(rows, fmt, price_band, scene=None, conn=None, nijikai_opts=None):
    """rows を指定フォーマットで標準出力へ。"""
    dicts = [row_to_dict(i, r, price_band, scene) for i, r in enumerate(rows, 1)]
    if fmt == "json":
        print(json.dumps(dicts, ensure_ascii=False, indent=2))
    elif fmt in ("csv", "tsv"):
        if not dicts:
            return
        delim = "\t" if fmt == "tsv" else ","
        w = csv.DictWriter(sys.stdout, fieldnames=list(dicts[0].keys()), delimiter=delim)
        w.writeheader()
        w.writerows(dicts)
    else:  # text
        print("=" * 80)
        for i, r in enumerate(rows, 1):
            print(format_row(i, r, price_band, scene))
            if conn is not None and nijikai_opts:
                cands = nijikai.find_nijikai(
                    conn, r["lat"], r["lng"], scene=scene,
                    max_distance_m=nijikai_opts["distance"],
                    limit=nijikai_opts["limit"],
                    exclude_shop_id=r["id"],
                )
                if cands:
                    print(f"   2次会候補 (徒歩{nijikai_opts['distance']}m圏):")
                    for d, nr in cands:
                        print(nijikai.format_nijikai_line(d, nr))


def bar(v, width=10):
    if v is None:
        return "データなし"
    return "█" * (v // 10) + "░" * (width - v // 10)


def build_where(preset, area_kw=None, fts=None, price_min=None, price_max=None,
                smoking=None, fully_private=None, mid_room=None, calm_min=None,
                special_min=None, ig_min=None, kwargs_extras=None):
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
    # 訪問済み/未訪問
    visited = kwargs_extras.get("visited") if kwargs_extras else None
    if visited is True:
        where.append("EXISTS (SELECT 1 FROM visits v WHERE v.shop_id = s.id)")
    elif visited is False:
        where.append("NOT EXISTS (SELECT 1 FROM visits v WHERE v.shop_id = s.id)")
    # Google評価
    if kwargs_extras:
        gmin = kwargs_extras.get("google_min")
        grev = kwargs_extras.get("google_reviews_min")
        if gmin is not None:
            where.append("EXISTS (SELECT 1 FROM google g WHERE g.shop_id=s.id AND g.rating >= ?)")
            args.append(gmin)
        if grev is not None:
            where.append("EXISTS (SELECT 1 FROM google g WHERE g.shop_id=s.id AND g.user_ratings_total >= ?)")
            args.append(grev)
    # 取得失敗除外
    where.append("(j.fetch_error IS NULL OR j.fetch_error = '')")
    return where, args, has_price_filter, (pmin, pmax), fts


def query(conn, preset_name=None, scene=None, sort=None, visited=None,
          google_min=None, google_reviews_min=None, **kwargs):
    preset = PRESETS.get(preset_name) if preset_name else None
    where, args, has_price, price_band, fts = build_where(
        preset,
        kwargs_extras={"visited": visited, "google_min": google_min,
                       "google_reviews_min": google_reviews_min},
        **kwargs,
    )
    scene = scene or (preset.get("scene") if preset else None)
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
    SELECT s.*, j.*,
           g.rating AS google_rating,
           g.user_ratings_total AS google_reviews,
           g.price_level AS google_price_level
    FROM shops s
    {fts_join}
    JOIN judgements j ON j.shop_id = s.id
    LEFT JOIN google g ON g.shop_id = s.id
    WHERE {where_sql} {price_join}
    """
    # ソート
    sort_mode = preset.get("sort") if preset else (sort or ("composite" if scene else "atmosphere"))
    band = price_band if has_price else None
    if sort_mode == "composite" and scene:
        rows = list(conn.execute(sql, args))
        rows.sort(
            key=lambda r: composite_score(
                r, json.loads(r["drink_course_prices_json"] or "[]"), scene, band
            ),
            reverse=True,
        )
        return rows, (preset, band, scene)
    if sort_mode == "atmosphere":
        sql += " ORDER BY COALESCE(j.atmosphere_calm,0) DESC, COALESCE(j.atmosphere_special,0) DESC, j.kaishoku_score DESC"
    elif sort_mode == "instagram":
        sql += " ORDER BY j.instagram_score DESC, COALESCE(j.atmosphere_special,0) DESC"
    elif sort_mode == "score":
        sql += " ORDER BY j.kaishoku_score DESC, j.drink_course_min_yen ASC"
    else:
        sql += " ORDER BY j.drink_course_min_yen ASC"
    return list(conn.execute(sql, args)), (preset, band, scene)


def format_row(idx, r, price_band=None, scene=None):
    drink_prices = json.loads(r["drink_course_prices_json"] or "[]")
    kaishoku_hits = json.loads(r["kaishoku_hits_json"] or "[]")
    ig_hits = json.loads(r["instagram_hits_json"] or "[]")
    fit = row_fit(r, scene, price_band)
    fit_str = f"  ★適合度 {fit}/100" if fit is not None else ""
    # Google評価（拡張がある場合のみ）
    try:
        g_rating = r["google_rating"]
        g_reviews = r["google_reviews"]
    except (IndexError, KeyError):
        g_rating = g_reviews = None
    if g_rating is not None:
        fit_str += f"  Google★{g_rating} ({g_reviews}件)"
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
        f"\n【{idx}】 {r['name']}{fit_str}",
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
    ap.add_argument("--scene", choices=["kaishoku", "date", "instagram"],
                    help="複合適合スコアのプロファイル（アドホック時。指定で自動的にcomposite順）")
    ap.add_argument("--sort", choices=["composite", "atmosphere", "instagram", "score", "price"])
    vg = ap.add_mutually_exclusive_group()
    vg.add_argument("--visited", action="store_true", help="訪問済みの店のみ")
    vg.add_argument("--unvisited", action="store_true", help="未訪問の店のみ")
    ap.add_argument("--with-nijikai", action="store_true",
                    help="各候補の徒歩圏で2次会候補を表示")
    ap.add_argument("--nijikai-distance", type=int, default=600,
                    help="2次会の徒歩距離(m, 既定600≒徒歩7-8分)")
    ap.add_argument("--nijikai-limit", type=int, default=3,
                    help="1候補あたり何件の2次会を出すか(既定3)")
    ap.add_argument("--google-min", type=float,
                    help="Google★最低値（例: 4.0）。要 google_enrich.py 事前実行")
    ap.add_argument("--google-reviews-min", type=int,
                    help="Google口コミ数最低（例: 30）")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--format", choices=["text", "csv", "tsv", "json"], default="text")
    ap.add_argument("--closures", action="store_true",
                    help="直近ingestで未確認＝閉店/移転候補の店を一覧（last_seen_atが最新より古い）")
    args = ap.parse_args()

    if args.list_presets:
        for k, v in PRESETS.items():
            print(f"  {k}: {v['description']}")
        return

    conn = dbmod.connect(args.db)

    if args.closures:
        latest = conn.execute("SELECT MAX(last_seen_at) FROM shops").fetchone()[0]
        rows = conn.execute(
            "SELECT name, address, last_seen_at, pc_url FROM shops "
            "WHERE last_seen_at < ? ORDER BY last_seen_at",
            (latest,),
        ).fetchall()
        if args.limit > 0:
            rows = rows[: args.limit]
        if args.format == "json":
            print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        elif args.format in ("csv", "tsv"):
            delim = "\t" if args.format == "tsv" else ","
            w = csv.writer(sys.stdout, delimiter=delim)
            w.writerow(["name", "address", "last_seen_at", "url"])
            w.writerows([tuple(r) for r in rows])
        else:
            print(f"# 閉店/移転候補（最新ingest {latest} 未確認）: {len(rows)}件\n")
            for r in rows:
                print(f"  - {r['name']} / {r['address']} (last_seen {r['last_seen_at'][:10]})")
        return
    visited_flag = True if args.visited else (False if args.unvisited else None)
    rows, (preset, price_band, scene) = query(
        conn,
        preset_name=args.preset,
        scene=args.scene,
        sort=args.sort,
        visited=visited_flag,
        google_min=args.google_min,
        google_reviews_min=args.google_reviews_min,
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

    nijikai_opts = ({"distance": args.nijikai_distance, "limit": args.nijikai_limit}
                    if args.with_nijikai else None)
    if args.format in ("csv", "tsv", "json"):
        emit(rows, args.format, price_band, scene)
        return

    if preset:
        print(f"# プリセット: {args.preset} — {preset['description']}")
    else:
        print(f"# アドホッククエリ")
    if args.limit > 0 and total > len(rows):
        print(f"# 該当: {total}件（上位{len(rows)}件を表示）\n")
    else:
        print(f"# 該当: {total}件\n")
    emit(rows, "text", price_band, scene, conn=conn, nijikai_opts=nijikai_opts)


if __name__ == "__main__":
    main()
