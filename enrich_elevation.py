#!/usr/bin/env python3
"""国土地理院 標高API（無料・キー不要）で店の標高を取得（G8）。

「夜景デート向け高層階」判定の裏取りに使える。海抜0mに近い湾岸 vs 高台、
ビル+標高で「夜景見える可能性」を補助評価できる。
"""
import argparse
import datetime as dt
import sys
import time

import requests
import db as dbmod

ENDPOINT = "https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php"
UA = "restaurant-filter/0.1"


def fetch_elevation(lat, lng, timeout=10, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(ENDPOINT, params={"lat": lat, "lon": lng, "outtype": "JSON"},
                             headers={"User-Agent": UA}, timeout=timeout)
            r.raise_for_status()
            d = r.json()
            v = d.get("elevation")
            if v == "-----" or v is None:
                return None
            return float(v)
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(1.5 * (2 ** attempt))
    return None


def main():
    ap = argparse.ArgumentParser(description="緯度経度から標高を取得")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--source", choices=["osm", "hotpepper", "all"], default="all")
    ap.add_argument("--delay", type=float, default=0.4)
    args = ap.parse_args()

    conn = dbmod.init_db(args.db)
    where = "s.lat IS NOT NULL AND j.elevation_m IS NULL"
    if args.source != "all":
        where += f" AND s.source = '{args.source}'"
    sql = (f"SELECT s.id, s.lat, s.lng FROM shops s "
           f"JOIN judgements j ON j.shop_id=s.id WHERE {where}")
    if args.limit > 0:
        sql += f" LIMIT {int(args.limit)}"
    rows = list(conn.execute(sql))
    print(f"標高取得対象: {len(rows):,}件", file=sys.stderr)

    n_ok = 0
    for i, r in enumerate(rows, 1):
        e = fetch_elevation(r["lat"], r["lng"])
        conn.execute("UPDATE judgements SET elevation_m=? WHERE shop_id=?",
                     (e, r["id"]))
        if e is not None:
            n_ok += 1
        if i % 200 == 0 or i == len(rows):
            conn.commit()
            print(f"  [{i}/{len(rows)}] 標高取得済 {n_ok:,}件", file=sys.stderr)
        time.sleep(args.delay)
    conn.commit()
    print(f"\n=== 完了: {n_ok:,}件 ===", file=sys.stderr)


if __name__ == "__main__":
    main()
