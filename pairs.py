#!/usr/bin/env python3
"""1次会×2次会の鉄板コンビを自動抽出してHTML化（E）。

シーン(kaishoku/date等)のプリセットで1次会候補上位Nを取り、各々の徒歩圏で
最良の2次会候補を nijikai.py で求めて、組合せの「総合点」順に並べる。

総合点 = 1次会の適合度 + 2次会の落ち着き度を正規化加算。

例:
  python pairs.py --preset kaishoku --top 5 --out output/kaishoku_pairs.html
  python pairs.py --preset date_shinjuku --top 5 --out output/date_pairs.html
"""
import argparse
import html
import json

import db as dbmod
import nijikai
from query import query, row_fit


def render(items, title):
    e = html.escape
    cards = []
    for idx, (first, fit1, second, dist) in enumerate(items, 1):
        sec_calm = second["atmosphere_calm"]
        sec_html = (
            f'<a href="{e(second["pc_url"])}" target="_blank" rel="noopener">'
            f'<b>{e(second["name"])}</b></a> '
            f'<span class="meta">{e(second["genre_name"])} / 落ち着き{sec_calm or "?"} / {dist}m</span>'
        ) if second else '<span class="none">適切な2次会候補なし</span>'

        cards.append(f"""
<div class="pair">
  <div class="rank">{idx}</div>
  <div class="content">
    <div class="first">
      <span class="fit">{fit1 or "?"}</span>
      <a href="{e(first['pc_url'])}" target="_blank" rel="noopener"><b>{e(first['name'])}</b></a>
      <div class="meta">{e(first['genre_name'])} / {e(first['address'])}</div>
    </div>
    <div class="arrow">↓</div>
    <div class="second">2次会: {sec_html}</div>
  </div>
</div>""")
    style = """
    body{font-family:-apple-system,"Hiragino Kaku Gothic ProN",sans-serif;margin:0;padding:18px;background:#fafafa;color:#222}
    h1{margin:0 0 4px;font-size:18px}
    .sub{color:#888;font-size:12px;margin-bottom:14px}
    .pair{display:flex;background:#fff;border:1px solid #ddd;border-radius:8px;padding:12px 14px;margin-bottom:10px}
    .rank{font-size:28px;font-weight:700;color:#c0392b;width:50px;text-align:center;flex-shrink:0}
    .content{flex:1}
    .first b{font-size:15px}
    .first a{color:#1a4ed8;text-decoration:none}
    .first .fit{display:inline-block;background:#c0392b;color:#fff;border-radius:14px;padding:2px 9px;font-size:12px;font-weight:700;margin-right:8px}
    .meta{color:#666;font-size:12px;margin-top:3px}
    .arrow{color:#999;font-size:14px;margin:6px 0 6px 60px}
    .second{font-size:13px;margin-left:60px;color:#444}
    .second b{font-size:14px;color:#1a4ed8}
    .none{color:#aaa;font-style:italic}
    """
    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<title>{e(title)}</title><style>{style}</style></head><body>
<h1>{e(title)}</h1>
<div class="sub">1次会×2次会の組合せ TOP{len(items)}（適合度×2次会落ち着き）</div>
{''.join(cards)}
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="1次会×2次会の鉄板コンビ生成")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--preset", required=True)
    ap.add_argument("--top", type=int, default=5, help="1次会候補上位N")
    ap.add_argument("--nijikai-distance", type=int, default=600)
    ap.add_argument("--out", default="output/pairs.html")
    args = ap.parse_args()

    conn = dbmod.connect(args.db)
    rows, (preset, price_band, scene) = query(conn, preset_name=args.preset)
    rows = rows[: args.top]
    if not rows:
        raise SystemExit("対象なし。プリセット条件を確認してください。")

    items = []
    for first in rows:
        fit1 = row_fit(first, scene, price_band)
        # 2次会候補1件取得（最も落ち着いた1件）
        cands = nijikai.find_nijikai(
            conn, first["lat"], first["lng"], scene=scene,
            max_distance_m=args.nijikai_distance, limit=1,
            exclude_shop_id=first["id"],
        )
        second = cands[0][1] if cands else None
        dist = cands[0][0] if cands else None
        items.append((first, fit1, second, dist))

    # 総合点 = fit1 + 2次会の落ち着き/100 * 20（最大20点ボーナス）
    items.sort(key=lambda it: (
        -(it[1] or 0) - (((it[2]["atmosphere_calm"] if it[2] else 0) or 0) / 5)
    ))

    title = f"鉄板コンビ TOP{args.top} — {preset['description']}"
    html_out = render(items, title)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"{args.out} を生成（{len(items)}組）")


if __name__ == "__main__":
    main()
