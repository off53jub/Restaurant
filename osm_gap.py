#!/usr/bin/env python3
"""OSM固有(HotPepperに無い)店から、website/phone付きの個人店を抽出してHTML化。

OSMには「個人店ほどタグ薄い」傾向はあるが、website か phone が付いている店は
公式サイト/Instagramへのリンクが取れるので、店の詳細はそこから確認できる。

例:
  python osm_gap.py --area 中野 --out output/osm_unique_nakano.html
  python osm_gap.py --area 港区 --area 中央区 --limit 50
"""
import argparse
import html
import json
import math
import re
from collections import defaultdict

import db as dbmod


CHAIN_KEYWORDS = [
    "スターバックス", "ドトール", "タリーズ", "カフェ・ベローチェ", "サンマルク",
    "上島珈琲", "エクセルシオール", "プロント", "コメダ",
    "マクドナルド", "モスバーガー", "ケンタッキー", "ロッテリア", "バーガーキング",
    "吉野家", "すき家", "松屋", "なか卯", "てんや",
    "大戸屋", "やよい軒", "日高屋", "ガスト", "サイゼリヤ", "ロイヤルホスト",
    "ジョナサン", "ココス", "デニーズ", "バーミヤン", "丸亀製麺", "はなまるうどん",
    "リンガーハット", "餃子の王将", "大阪王将", "幸楽苑", "山岡家", "壱角家",
    "ファミリーマート", "セブン-イレブン", "ローソン", "ミニストップ",
    "BECK'S COFFEE", "あじさい茶屋",
]


def is_chain(name):
    if not name:
        return False
    return any(k in name for k in CHAIN_KEYWORDS)


def haversine_m(a_lat, a_lng, b_lat, b_lng):
    R = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat); dl = math.radians(b_lng - a_lng)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(a))


def find_unique_osm(conn, area_kw=None, require_contact=True,
                    exclude_chains=True, max_dup_distance_m=50):
    """OSM固有店（HotPepperと重複しない）を返す。"""
    osm_rows = list(conn.execute(
        "SELECT id, name, address, lat, lng, raw_json, pc_url "
        "FROM shops WHERE source='osm' AND lat IS NOT NULL"
    ))
    hp_rows = list(conn.execute(
        "SELECT name, lat, lng FROM shops "
        "WHERE source='hotpepper' AND lat IS NOT NULL"
    ))
    hp_by_bucket = defaultdict(list)
    for r in hp_rows:
        if r["lat"]:
            hp_by_bucket[round(r["lat"], 2)].append(r)

    out = []
    for o in osm_rows:
        # エリア絞り込み
        if area_kw:
            addr = o["address"] or ""
            tags = json.loads(o["raw_json"]).get("tags", {})
            haystack = addr + " " + (tags.get("addr:city") or "") + " " + (tags.get("addr:district") or "")
            if not any(k in haystack for k in area_kw):
                # 緯度経度ベースの近似マッチも試す
                continue

        if exclude_chains and is_chain(o["name"]):
            continue

        tags = json.loads(o["raw_json"]).get("tags", {})
        if require_contact:
            if not (tags.get("website") or tags.get("contact:website") or tags.get("phone")):
                continue

        # HotPepperと重複チェック
        dup = False
        for b in (round(o["lat"], 2),
                  round(o["lat"] + 0.01, 2),
                  round(o["lat"] - 0.01, 2)):
            for h in hp_by_bucket.get(b, []):
                if haversine_m(o["lat"], o["lng"], h["lat"], h["lng"]) > max_dup_distance_m:
                    continue
                if o["name"] and h["name"]:
                    if o["name"] in h["name"] or h["name"] in o["name"]:
                        dup = True; break
                else:
                    dup = True; break
            if dup: break
        if dup:
            continue
        out.append((o, tags))
    return out


# OSM cuisine → 日本語
CUISINE_JA = {
    "japanese": "和食", "sushi": "寿司", "ramen": "ラーメン", "soba": "そば",
    "udon": "うどん", "tempura": "天ぷら", "yakiniku": "焼肉", "yakitori": "焼鳥",
    "izakaya": "居酒屋", "japanese_curry": "カレー(和)", "japanese_western": "洋食",
    "italian": "イタリアン", "french": "フレンチ", "spanish": "スペイン料理",
    "chinese": "中華", "korean": "韓国料理", "thai": "タイ料理",
    "indian": "インド料理", "vietnamese": "ベトナム料理",
    "coffee_shop": "カフェ", "cafe": "カフェ", "tea": "茶店",
    "burger": "ハンバーガー", "pizza": "ピザ", "steak_house": "ステーキ",
    "barbecue": "BBQ", "seafood": "魚介", "dessert": "スイーツ",
    "international": "多国籍",
}


def render_html(items, title, limit):
    e = html.escape
    items = items[:limit]
    cards = []
    for el, tags in items:
        name = e(el["name"] or "(名前未登録)")
        cuisine = tags.get("cuisine", "").split(";")[0]
        cuisine_ja = CUISINE_JA.get(cuisine, cuisine)
        amenity = tags.get("amenity", "")
        addr = e(el["address"] or "(住所未登録)")
        website = tags.get("website") or tags.get("contact:website")
        phone = tags.get("phone")
        hours = tags.get("opening_hours", "")
        desc = tags.get("description", "")
        osm_url = f"https://www.openstreetmap.org/{el['id'].replace('osm:', '')}"
        gmap_url = f"https://www.google.com/maps/search/?api=1&query={el['lat']},{el['lng']}"
        web_html = (f'<a class="ext" href="{e(website)}" target="_blank" rel="noopener">'
                    f'公式/SNS →</a>' if website else "")
        phone_html = (f'<a class="ext" href="tel:{e(phone.replace(" ",""))}">📞 {e(phone)}</a>'
                      if phone else "")
        hours_html = f'<div class="hours">⏰ {e(hours[:60])}</div>' if hours else ""
        desc_html = f'<div class="desc">{e(desc[:120])}</div>' if desc else ""
        cards.append(f'''
<div class="card">
  <h3>{name}</h3>
  <div class="meta">{e(cuisine_ja or amenity)}</div>
  <div class="addr">{addr}</div>
  {hours_html}{desc_html}
  <div class="links">
    {web_html}{phone_html}
    <a class="ext" href="{gmap_url}" target="_blank" rel="noopener">🗺️ 地図</a>
    <a class="ext" href="{osm_url}" target="_blank" rel="noopener">OSM →</a>
  </div>
</div>''')
    style = """
    body{font-family:-apple-system,"Hiragino Kaku Gothic ProN",sans-serif;margin:0;padding:18px;background:#fafafa}
    h1{margin:0 0 4px;font-size:18px}
    .sub{color:#888;font-size:12px;margin-bottom:14px}
    .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
    .card{background:#fff;border:1px solid #e1e1e1;border-radius:8px;padding:12px}
    .card h3{margin:0 0 5px;font-size:15px}
    .meta{display:inline-block;background:#f0f0f0;border-radius:4px;padding:1px 7px;font-size:11px;color:#555;margin-bottom:5px}
    .addr{color:#666;font-size:12px;margin-bottom:5px}
    .hours{color:#777;font-size:11.5px;margin-top:4px}
    .desc{color:#555;font-size:12px;margin-top:5px;line-height:1.4}
    .links{margin-top:8px;display:flex;gap:5px;flex-wrap:wrap}
    .links a{font-size:11px;background:#1a4ed8;color:#fff;text-decoration:none;padding:3px 8px;border-radius:4px}
    .links a:hover{background:#0c3ac4}
    """
    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<title>{e(title)}</title><style>{style}</style></head><body>
<h1>{e(title)}</h1>
<div class="sub">{len(items)}件 / HotPepper未掲載のOSM個人店候補（チェーン除外・連絡先あり）</div>
<div class="grid">{''.join(cards)}</div>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="OSM固有店（HP未掲載）の発掘HTML")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--area", action="append", help="区/エリア名でフィルタ（複数可）")
    ap.add_argument("--all-tags-only", action="store_true",
                    help="phone/website 必須ではなく、すべて出す")
    ap.add_argument("--include-chains", action="store_true")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--out", default="output/osm_gap.html")
    args = ap.parse_args()

    conn = dbmod.connect(args.db)
    items = find_unique_osm(
        conn, area_kw=args.area,
        require_contact=not args.all_tags_only,
        exclude_chains=not args.include_chains,
    )
    title = "OSM固有店（HotPepperにない個人店候補）"
    if args.area:
        title += f" — {'/'.join(args.area)}"
    out_html = render_html(items, title, args.limit)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(out_html)
    print(f"{args.out} を生成（{min(len(items), args.limit)}/{len(items)}件）")


if __name__ == "__main__":
    main()
