#!/usr/bin/env python3
"""query.py と同じ条件で抽出し、写真・地図・適合度付きの自己完結HTMLを生成。

例:
  python report.py --preset date_shinjuku --limit 20 --out date.html
  python report.py --area 銀座 --price-min 6000 --price-max 9000 --scene kaishoku
"""
import argparse
import html
import json

import db as dbmod
from query import query, row_fit
import nijikai


def photo_url(raw_json):
    """raw_json から写真URLを取り出す（pc.l → pc.m → mobile → 空）。"""
    try:
        p = json.loads(raw_json).get("photo", {})
        return (p.get("pc", {}).get("l") or p.get("pc", {}).get("m")
                or p.get("mobile", {}).get("l") or "")
    except Exception:
        return ""


def atm_bar(label, v):
    if v is None:
        return f'<div class="atm"><span>{label}</span><i>データなし</i></div>'
    return (
        f'<div class="atm"><span>{label}</span>'
        f'<div class="track"><div class="fill" style="width:{v}%"></div></div>'
        f'<b>{v}</b></div>'
    )


def nijikai_block_html(cands):
    if not cands:
        return ""
    e = html.escape
    items = []
    for d, r in cands:
        calm = r["atmosphere_calm"]
        calm_str = f"落ち着き{calm}" if calm is not None else ""
        items.append(
            f'<a class="nk-item" href="{e(r["pc_url"])}" target="_blank" rel="noopener">'
            f'<b>{e(r["name"])}</b>'
            f'<span class="nk-meta">{d}m · {e(r["genre_name"])} · {calm_str}</span>'
            f'</a>'
        )
    return f'<div class="nijikai"><div class="nk-label">2次会候補</div>{"".join(items)}</div>'


def card_html(idx, r, price_band, scene, nijikai_cands=None):
    e = html.escape
    drink_prices = json.loads(r["drink_course_prices_json"] or "[]")
    band_str = ""
    if price_band:
        lo, hi = price_band
        inb = [p for p in drink_prices if lo <= p <= hi]
        if inb:
            band_str = " / ".join(f"{p:,}円" for p in inb)
    all_str = " / ".join(f"{p:,}円" for p in drink_prices[:6]) or "—"
    fit = row_fit(r, scene, price_band)
    fit_badge = f'<div class="fit">{fit}</div>' if fit is not None else ""
    g_rating = g_reviews = None
    try:
        g_rating = r["google_rating"]; g_reviews = r["google_reviews"]
    except (IndexError, KeyError):
        pass
    google_html = (f'<div class="google">G★{g_rating} <small>({g_reviews}件)</small></div>'
                   if g_rating is not None else "")
    img = photo_url(r["raw_json"])
    img_html = (f'<img loading="lazy" src="{e(img)}" alt="">' if img
                else '<div class="noimg">No Photo</div>')
    smoke = {"allowed": "🚬可", "partial": "分煙", "forbidden": "禁煙",
             "unknown": "—"}.get(r["smoking_at_seat"], "—")
    priv = "完全個室" if r["fully_private_room"] else "—"
    mid = "5-8名個室" if r["mid_room_ok"] else ""
    nijikai_html = nijikai_block_html(nijikai_cands or [])
    return f"""
<div class="card" id="card-{idx}">
  <div class="thumb">{img_html}{fit_badge}</div>
  <div class="body">
    <h3><span class="rank">{idx}</span>
        <a href="{e(r['pc_url'])}" target="_blank" rel="noopener">{e(r['name'])}</a>
        {google_html}</h3>
    <div class="meta">{e(r['genre_name'])}・{e(r['address'])}</div>
    <div class="meta small">{e(r['access'] or '')}</div>
    {atm_bar('落ち着き', r['atmosphere_calm'])}
    {atm_bar('特別感', r['atmosphere_special'])}
    <div class="tags">
      <span>飲放: {e(band_str or all_str)}</span>
      <span>{priv}</span>{f'<span>{mid}</span>' if mid else ''}
      <span>{smoke}</span>
      <span>会食{r['kaishoku_score']}</span>
      <span>映え{r['instagram_score']}</span>
    </div>
    {nijikai_html}
  </div>
</div>"""


def build_html(rows, title, price_band, scene, conn=None, nijikai_opts=None):
    markers = []
    cards = []
    for i, r in enumerate(rows, 1):
        nk = None
        if conn is not None and nijikai_opts:
            nk = nijikai.find_nijikai(
                conn, r["lat"], r["lng"], scene=scene,
                max_distance_m=nijikai_opts["distance"],
                limit=nijikai_opts["limit"],
                exclude_shop_id=r["id"],
            )
        cards.append(card_html(i, r, price_band, scene, nk))
        if r["lat"] and r["lng"]:
            fit = row_fit(r, scene, price_band)
            markers.append({
                "lat": r["lat"], "lng": r["lng"], "i": i,
                "name": r["name"], "fit": fit, "url": r["pc_url"],
            })
    markers_json = json.dumps(markers, ensure_ascii=False)
    if markers:
        clat = sum(m["lat"] for m in markers) / len(markers)
        clng = sum(m["lng"] for m in markers) / len(markers)
    else:
        clat, clng = 35.68, 139.76
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 :root{{--bd:#e3e3e3;--mut:#777;--accent:#c0392b}}
 *{{box-sizing:border-box}} body{{margin:0;font-family:-apple-system,"Hiragino Kaku Gothic ProN",sans-serif;color:#222;background:#fafafa}}
 header{{padding:14px 18px;background:#fff;border-bottom:1px solid var(--bd);position:sticky;top:0;z-index:500}}
 header h1{{margin:0;font-size:17px}} header .sub{{color:var(--mut);font-size:12px;margin-top:3px}}
 #map{{height:340px;width:100%}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px;padding:16px;max-width:1280px;margin:0 auto}}
 .card{{background:#fff;border:1px solid var(--bd);border-radius:10px;overflow:hidden;display:flex;flex-direction:column}}
 .thumb{{position:relative;height:170px;background:#eee}}
 .thumb img{{width:100%;height:100%;object-fit:cover;display:block}}
 .noimg{{display:flex;align-items:center;justify-content:center;height:100%;color:#bbb;font-size:13px}}
 .fit{{position:absolute;top:8px;right:8px;background:var(--accent);color:#fff;font-weight:700;border-radius:18px;padding:4px 9px;font-size:13px;box-shadow:0 1px 4px rgba(0,0,0,.3)}}
 .body{{padding:11px 13px;flex:1}}
 h3{{margin:0 0 5px;font-size:15px;line-height:1.35}}
 h3 a{{color:#1a4ed8;text-decoration:none}} h3 a:hover{{text-decoration:underline}}
 .rank{{display:inline-block;background:#333;color:#fff;border-radius:5px;font-size:11px;padding:1px 6px;margin-right:5px;vertical-align:middle}}
 .meta{{color:#555;font-size:12px;margin:2px 0}} .meta.small{{color:var(--mut)}}
 .atm{{display:flex;align-items:center;gap:7px;margin:4px 0;font-size:11px}}
 .atm span{{width:46px;color:var(--mut)}} .atm b{{width:24px;text-align:right}}
 .atm .track{{flex:1;height:7px;background:#eee;border-radius:4px;overflow:hidden}}
 .atm .fill{{height:100%;background:linear-gradient(90deg,#f0a,#c0392b)}}
 .tags{{margin-top:8px;display:flex;flex-wrap:wrap;gap:5px}}
 .tags span{{background:#f0f0f0;border-radius:5px;padding:2px 7px;font-size:11px;color:#444}}
 .nijikai{{margin-top:10px;padding-top:8px;border-top:1px dashed #ddd}}
 .nk-label{{font-size:11px;color:var(--mut);margin-bottom:4px}}
 .nk-item{{display:block;padding:5px 7px;background:#fafafa;border:1px solid #eee;border-radius:6px;margin-bottom:4px;text-decoration:none;color:#222}}
 .nk-item:hover{{background:#f0f0f0}} .nk-item b{{font-size:12px}}
 .nk-meta{{display:block;color:var(--mut);font-size:10.5px;margin-top:1px}}
 .google{{display:inline-block;background:#fff8e1;color:#b8860b;border:1px solid #ffd54f;border-radius:4px;padding:1px 6px;font-size:11px;font-weight:600;margin-left:6px;vertical-align:middle}}
 .google small{{color:#999;font-weight:400}}
</style></head><body>
<header><h1>{html.escape(title)}</h1><div class="sub">{len(rows)}件 ・ 適合度＝シーン複合スコア ・ ピンクリックでカードへ</div></header>
<div id="map"></div>
<div class="grid">{''.join(cards)}</div>
<script>
 var map=L.map('map').setView([{clat},{clng}],13);
 L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
   {{maxZoom:19,attribution:'&copy; OpenStreetMap'}}).addTo(map);
 var ms={markers_json}, group=[];
 ms.forEach(function(m){{
   var mk=L.marker([m.lat,m.lng]).addTo(map);
   mk.bindPopup('<b>'+m.i+'. '+m.name+'</b>'+(m.fit!=null?' ('+m.fit+')':'')+
     '<br><a href="#card-'+m.i+'">カードへ</a> / <a href="'+m.url+'" target="_blank">予約</a>');
   group.push([m.lat,m.lng]);
 }});
 if(group.length) map.fitBounds(group,{{padding:[40,40],maxZoom:15}});
</script>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="抽出結果を写真・地図付きHTMLに出力")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--preset")
    ap.add_argument("--scene", choices=["kaishoku", "date", "instagram"])
    ap.add_argument("--sort", choices=["composite", "atmosphere", "instagram", "score", "price"])
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
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--out", default="report.html")
    ap.add_argument("--title")
    ap.add_argument("--with-nijikai", action="store_true",
                    help="各候補の徒歩圏で2次会候補をカード内に表示")
    ap.add_argument("--nijikai-distance", type=int, default=600)
    ap.add_argument("--nijikai-limit", type=int, default=3)
    args = ap.parse_args()

    conn = dbmod.connect(args.db)
    rows, (preset, price_band, scene) = query(
        conn, preset_name=args.preset, scene=args.scene, sort=args.sort,
        area_kw=args.area, fts=args.fts,
        price_min=args.price_min, price_max=args.price_max, smoking=args.smoking,
        fully_private=args.fully_private or None, mid_room=args.mid_room or None,
        calm_min=args.calm_min, special_min=args.special_min, ig_min=args.ig_min,
    )
    if args.limit > 0:
        rows = rows[: args.limit]

    title = args.title or (preset["description"] if preset else "レストラン候補")
    nk_opts = ({"distance": args.nijikai_distance, "limit": args.nijikai_limit}
               if args.with_nijikai else None)
    htmls = build_html(rows, title, price_band, scene, conn=conn, nijikai_opts=nk_opts)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(htmls)
    print(f"{args.out} を生成（{len(rows)}件）")


if __name__ == "__main__":
    main()
