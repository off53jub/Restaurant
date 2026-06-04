#!/usr/bin/env python3
"""緯度経度から東京23区名を逆引きして judgements.ward に保存（H4）。

国土地理院 逆ジオコーディングAPI（無料・キー不要）で muniCd を取得し、
23区の市区町村コード辞書で区名に変換する。
住所から区が取れる店（多くのHotPepper店）はAPIを叩かずに住所優先で埋める。
"""
import argparse
import datetime as dt
import re
import sys
import time

import requests

import db as dbmod

GSI_URL = "https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress"
UA = "restaurant-filter/0.1"

# 東京23区の muniCd → 区名
MUNI_CD_WARD = {
    "13101": "千代田区", "13102": "中央区", "13103": "港区", "13104": "新宿区",
    "13105": "文京区", "13106": "台東区", "13107": "墨田区", "13108": "江東区",
    "13109": "品川区", "13110": "目黒区", "13111": "大田区", "13112": "世田谷区",
    "13113": "渋谷区", "13114": "中野区", "13115": "杉並区", "13116": "豊島区",
    "13117": "北区", "13118": "荒川区", "13119": "板橋区", "13120": "練馬区",
    "13121": "足立区", "13122": "葛飾区", "13123": "江戸川区",
}

WARD_RE = re.compile(
    r"(千代田区|中央区|港区|新宿区|文京区|台東区|墨田区|江東区|品川区|目黒区|"
    r"大田区|世田谷区|渋谷区|中野区|杉並区|豊島区|北区|荒川区|板橋区|練馬区|"
    r"足立区|葛飾区|江戸川区)"
)


def ward_from_address(address):
    m = WARD_RE.search(address or "")
    return m.group(1) if m else None


def ward_from_gsi(lat, lng, timeout=10, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(GSI_URL, params={"lat": lat, "lon": lng},
                             headers={"User-Agent": UA}, timeout=timeout)
            r.raise_for_status()
            muni = (r.json().get("results") or {}).get("muniCd")
            return MUNI_CD_WARD.get(str(muni))  # 23区外はNone
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(1.5 * (2 ** attempt))
    return None


def main():
    ap = argparse.ArgumentParser(description="緯度経度→区名 逆ジオコーディング")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.3, help="GSI APIマナー")
    ap.add_argument("--source", help="このsourceの店だけ（例: osm）")
    args = ap.parse_args()

    conn = dbmod.init_db(args.db)
    where = ["(j.ward IS NULL OR j.ward = '')"]
    params = []
    if args.source:
        where.append("s.source = ?")
        params.append(args.source)
    sql = (f"SELECT s.id, s.address, s.lat, s.lng FROM shops s "
           f"JOIN judgements j ON j.shop_id=s.id WHERE {' AND '.join(where)}")
    rows = list(conn.execute(sql, params))
    if args.limit > 0:
        rows = rows[: args.limit]
    print(f"逆ジオ対象: {len(rows)}件", file=sys.stderr)

    by_addr = by_api = none_n = 0
    for i, r in enumerate(rows, 1):
        ward = ward_from_address(r["address"])
        if ward:
            by_addr += 1
        elif r["lat"] and r["lng"]:
            ward = ward_from_gsi(r["lat"], r["lng"])
            if ward:
                by_api += 1
            time.sleep(args.delay)
        if not ward:
            none_n += 1
            ward = ""  # 処理済みの印（23区外/不明）
        conn.execute("UPDATE judgements SET ward=? WHERE shop_id=?", (ward, r["id"]))
        if i % 100 == 0 or i == len(rows):
            conn.commit()
            print(f"  [{i}/{len(rows)}] 住所={by_addr} API={by_api} 区外/不明={none_n}",
                  file=sys.stderr)
    conn.commit()
    print(f"\n=== 完了: 住所判定{by_addr} / API判定{by_api} / 区外不明{none_n} ===",
          file=sys.stderr)


if __name__ == "__main__":
    main()
