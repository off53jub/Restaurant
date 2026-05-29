#!/usr/bin/env python3
"""候補2〜5店を横並びの比較表で1枚のHTMLに出力。

人に「これとこれ、どっち？」と送る用。shop_idを直指定するか、
query.pyと同じ条件で抽出した上位を比較する。

例:
  python compare.py --ids J003559227 J001238039 J000711062 --out cmp.html
  python compare.py --preset kaishoku --top 3 --out cmp.html
  python compare.py --area 銀座 --scene date --top 4 --with-nijikai --out cmp.html
"""
import argparse
import html
import json
from typing import List

import db as dbmod
import nijikai
from query import query, row_fit
from score import composite_score, SCENE_PROFILES


def fetch_shops_by_ids(conn, shop_ids):
    rows = []
    for sid in shop_ids:
        r = conn.execute(
            "SELECT s.*, j.* FROM shops s JOIN judgements j ON j.shop_id=s.id WHERE s.id=?",
            (sid,),
        ).fetchone()
        if not r:
            raise SystemExit(f"shop_id {sid} がDBに無いか未enrich")
        rows.append(r)
    return rows


def photo_url(raw_json):
    try:
        p = json.loads(raw_json).get("photo", {})
        return (p.get("pc", {}).get("l") or p.get("pc", {}).get("m") or "")
    except Exception:
        return ""


def render(rows, scene, price_band, conn, nijikai_opts):
    """比較表HTML。各店を1列、評価軸を行に。"""
    e = html.escape
    n = len(rows)
    cols = "".join(f"<th>{i+1}</th>" for i in range(n))

    def row_html(label, cells, klass=""):
        tds = "".join(f'<td class="{klass}">{c}</td>' for c in cells)
        return f'<tr><th class="row-label">{label}</th>{tds}</tr>'

    # ヘッダ（写真+店名+リンク）
    head_cells = []
    for r in rows:
        img = photo_url(r["raw_json"])
        img_html = (f'<img src="{e(img)}" alt="">' if img
                    else '<div class="noimg">No Photo</div>')
        head_cells.append(
            f'<div class="shop-head">{img_html}'
            f'<a href="{e(r["pc_url"])}" target="_blank" rel="noopener">'
            f'<b>{e(r["name"])}</b></a><div class="addr">{e(r["address"] or "")}</div></div>'
        )
    head_row = "<tr><th></th>" + "".join(f"<td>{c}</td>" for c in head_cells) + "</tr>"

    # 適合度（シーン別）
    fit_rows = []
    if scene:
        fit_cells = []
        for r in rows:
            v = row_fit(r, scene, price_band)
            color = "#c0392b" if v and v >= 70 else ("#e67e22" if v and v >= 50 else "#999")
            fit_cells.append(
                f'<div class="bignum" style="color:{color}">{v if v is not None else "—"}'
                f'<small>/100</small></div>'
            )
        fit_rows.append(row_html(f"適合度({scene})", fit_cells, "center"))

    # 他のシーン適合度（参考）
    other_scenes = [s for s in SCENE_PROFILES if s != scene]
    for s in other_scenes:
        cells = []
        for r in rows:
            prices = json.loads(r["drink_course_prices_json"] or "[]")
            cells.append(str(composite_score(r, prices, s)))
        fit_rows.append(row_html(f"  参考: {s}", cells, "center small-num"))

    body_rows = []
    body_rows.append(row_html("ジャンル", [e(r["genre_name"] or "—") for r in rows]))

    def price_summary(r):
        prices = json.loads(r["drink_course_prices_json"] or "[]")
        if not prices:
            return "—"
        in_band = ""
        if price_band:
            lo, hi = price_band
            band = [p for p in prices if lo <= p <= hi]
            if band:
                in_band = f' <b style="color:#c0392b">該当:{",".join(f"{p:,}" for p in band)}</b>'
        return f"{prices[0]:,}〜{prices[-1]:,}{in_band}"
    body_rows.append(row_html("飲放コース", [price_summary(r) for r in rows]))
    body_rows.append(row_html("予算(平均)", [e(r["budget_name"] or "—") for r in rows]))

    def atm_cell(r, key):
        v = r[key]
        if v is None:
            return "—"
        return (f'<div class="bar"><div class="fill" style="width:{v}%"></div>'
                f'<span>{v}</span></div>')
    body_rows.append(row_html("落ち着き", [atm_cell(r, "atmosphere_calm") for r in rows]))
    body_rows.append(row_html("特別な日", [atm_cell(r, "atmosphere_special") for r in rows]))
    body_rows.append(row_html("インスタ度",
                              [f'{r["instagram_score"]}/8' for r in rows]))
    body_rows.append(row_html("会食キーワード",
                              [f'{r["kaishoku_score"]}/13' for r in rows]))
    body_rows.append(row_html("完全個室",
                              ["○" if r["fully_private_room"] else "—" for r in rows]))
    body_rows.append(row_html("5-8名個室",
                              [(r["mid_room_evidence"] or "—")[:24] for r in rows]))
    smoke_map = {"allowed": "○喫煙可", "partial": "△分煙",
                 "forbidden": "×禁煙", "unknown": "?"}
    body_rows.append(row_html("喫煙",
                              [smoke_map.get(r["smoking_at_seat"], "—") for r in rows]))
    body_rows.append(row_html("アクセス",
                              [e((r["access"] or "")[:40]) for r in rows]))

    if nijikai_opts:
        nk_cells = []
        for r in rows:
            cands = nijikai.find_nijikai(
                conn, r["lat"], r["lng"], scene=scene,
                max_distance_m=nijikai_opts["distance"],
                limit=nijikai_opts["limit"], exclude_shop_id=r["id"],
            )
            if not cands:
                nk_cells.append("—")
            else:
                items = "".join(
                    f'<div>{e(nr["name"][:24])} <small>{d}m</small></div>'
                    for d, nr in cands
                )
                nk_cells.append(items)
        body_rows.append(row_html(f"2次会({nijikai_opts['distance']}m)", nk_cells, "small"))

    style = """
    body{font-family:-apple-system,"Hiragino Kaku Gothic ProN",sans-serif;margin:0;padding:18px;background:#fafafa;color:#222}
    h1{margin:0 0 14px;font-size:18px}
    table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #ddd;border-radius:8px;overflow:hidden}
    th,td{border:1px solid #eee;padding:9px 11px;font-size:13px;vertical-align:top}
    th{background:#f5f5f5;font-weight:600}
    th.row-label{background:#fafafa;width:120px;text-align:right;color:#666;font-size:12px}
    .shop-head img{width:100%;max-height:120px;object-fit:cover;border-radius:4px;display:block}
    .shop-head .noimg{height:90px;background:#eee;display:flex;align-items:center;justify-content:center;color:#bbb;border-radius:4px}
    .shop-head a{display:block;margin-top:6px;color:#1a4ed8;text-decoration:none}
    .shop-head .addr{color:#777;font-size:11px;margin-top:3px}
    .center{text-align:center} .small{font-size:11px} .small-num{color:#999;font-size:12px}
    .bignum{font-size:22px;font-weight:700} .bignum small{font-size:11px;color:#999;font-weight:400}
    .bar{position:relative;height:18px;background:#eee;border-radius:4px;overflow:hidden}
    .bar .fill{height:100%;background:linear-gradient(90deg,#f0a,#c0392b)}
    .bar span{position:absolute;top:0;left:6px;line-height:18px;font-size:11px;color:#fff;text-shadow:0 0 2px rgba(0,0,0,.5)}
    """
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>店舗比較 ({n}店)</title>
<style>{style}</style></head><body>
<h1>店舗比較（{n}店{f' / シーン: {scene}' if scene else ''}）</h1>
<table>
  <tr><th></th>{cols}</tr>
  {head_row}
  {''.join(fit_rows)}
  {''.join(body_rows)}
</table>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="候補店の比較HTML")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--ids", nargs="+", help="比較したい shop_id を直接指定")
    # query.py 互換のフィルタ
    ap.add_argument("--preset")
    ap.add_argument("--scene", choices=["kaishoku", "date", "instagram"])
    ap.add_argument("--fts")
    ap.add_argument("--area", action="append")
    ap.add_argument("--price-min", type=int)
    ap.add_argument("--price-max", type=int)
    ap.add_argument("--smoking", choices=["any", "allowed", "partial_ok"])
    ap.add_argument("--fully-private", action="store_true")
    ap.add_argument("--mid-room", action="store_true")
    ap.add_argument("--calm-min", type=int)
    ap.add_argument("--special-min", type=int)
    ap.add_argument("--ig-min", type=int)
    ap.add_argument("--top", type=int, default=3, help="クエリ結果の上位N店を比較(2-5推奨)")
    ap.add_argument("--with-nijikai", action="store_true")
    ap.add_argument("--nijikai-distance", type=int, default=600)
    ap.add_argument("--nijikai-limit", type=int, default=3)
    ap.add_argument("--out", default="compare.html")
    args = ap.parse_args()

    if args.top > 5 or args.top < 2:
        print(f"WARN: --top {args.top} は推奨外（2-5）", flush=True)

    conn = dbmod.connect(args.db)
    if args.ids:
        rows = fetch_shops_by_ids(conn, args.ids)
        scene = args.scene
        price_band = (args.price_min, args.price_max) if args.price_min and args.price_max else None
    else:
        rows, (preset, price_band, scene) = query(
            conn, preset_name=args.preset, scene=args.scene,
            area_kw=args.area, fts=args.fts,
            price_min=args.price_min, price_max=args.price_max, smoking=args.smoking,
            fully_private=args.fully_private or None, mid_room=args.mid_room or None,
            calm_min=args.calm_min, special_min=args.special_min, ig_min=args.ig_min,
        )
        rows = rows[: args.top]

    if not rows:
        raise SystemExit("比較対象が0件")

    nk_opts = ({"distance": args.nijikai_distance, "limit": args.nijikai_limit}
               if args.with_nijikai else None)
    html_text = render(rows, scene, price_band, conn, nk_opts)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html_text)
    print(f"{args.out} を生成（{len(rows)}店比較）")


if __name__ == "__main__":
    main()
