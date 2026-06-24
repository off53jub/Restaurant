#!/usr/bin/env python3
"""東京都オープンデータカタログから飲食店関連CSVを取込（G6、無料）。

カタログ: https://catalog.data.metro.tokyo.lg.jp/
本スクリプトはダウンロード済みCSVを --csv で渡して取り込む形式。
（カタログAPI叩くには種類ごとに項目マッピングが要るので、現実的にはこの形）

例:
  python ingest_tokyo_opendata.py --csv data/tokyo_tourist_restaurants.csv \
      --dataset-name '東京都観光案内施設'

CSV列名は自動推定。少なくとも「名称/住所」っぽい列があればOK。
ingest_foods.py と類似だが source='tokyo' プレフィックスで管理する。
"""
import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

import db as dbmod

ID_PREFIX = "tokyo:"

WARD_RE = re.compile(
    r"(千代田区|中央区|港区|新宿区|文京区|台東区|墨田区|江東区|品川区|目黒区|"
    r"大田区|世田谷区|渋谷区|中野区|杉並区|豊島区|北区|荒川区|板橋区|練馬区|"
    r"足立区|葛飾区|江戸川区)"
)

NAME_ALIASES = ["名称", "店舗名", "施設名", "施設名称", "事業者名", "屋号"]
ADDR_ALIASES = ["所在地", "住所", "施設所在地", "事業所所在地"]
LAT_ALIASES = ["緯度", "latitude", "Lat", "Y"]
LNG_ALIASES = ["経度", "longitude", "Lng", "X"]


def find_col(header, aliases):
    for a in aliases:
        for h in header:
            if a in h:
                return h
    return None


def main():
    ap = argparse.ArgumentParser(description="東京都オープンデータCSV取込（飲食関連）")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--dataset-name", required=True,
                    help="データセット識別名（id プレフィクスの一部に）")
    ap.add_argument("--encoding", default="utf-8-sig")
    ap.add_argument("--wards-only", action="store_true", default=True)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    path = Path(args.csv)
    if not path.exists():
        raise SystemExit(f"CSVが見つかりません: {path}")

    conn = dbmod.init_db(args.db)
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    with open(path, encoding=args.encoding, newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        name_col = find_col(header, NAME_ALIASES)
        addr_col = find_col(header, ADDR_ALIASES)
        lat_col = find_col(header, LAT_ALIASES)
        lng_col = find_col(header, LNG_ALIASES)
        if not name_col or not addr_col:
            raise SystemExit(
                f"店名/住所列が見つかりません。\n"
                f"  ヘッダ: {header}\n  検出: name={name_col} addr={addr_col}")
        print(f"列: name={name_col} addr={addr_col} lat={lat_col} lng={lng_col}",
              file=sys.stderr)

        new_n = upd_n = skip = 0
        seen = 0
        for row in reader:
            seen += 1
            if args.limit and seen > args.limit:
                break
            name = (row.get(name_col) or "").strip()
            address = (row.get(addr_col) or "").strip()
            if not name or not address:
                continue
            wm = WARD_RE.search(address)
            if args.wards_only and not wm:
                skip += 1
                continue
            try:
                lat = float(row.get(lat_col, "")) if lat_col else None
                lng = float(row.get(lng_col, "")) if lng_col else None
            except (ValueError, TypeError):
                lat = lng = None
            sid = ID_PREFIX + re.sub(r"\s+", "",
                                     f"{args.dataset_name}_{name}_{address}")[:80]
            raw = json.dumps({"name": name, "address": address,
                              "dataset": args.dataset_name, "row": row},
                             ensure_ascii=False)
            ex = conn.execute("SELECT 1 FROM shops WHERE id=?", (sid,)).fetchone()
            if ex:
                conn.execute("UPDATE shops SET last_seen_at=? WHERE id=?", (now, sid))
                upd_n += 1
            else:
                conn.execute(
                    "INSERT INTO shops(id,name,name_kana,address,station_name,lat,lng,"
                    "genre_name,budget_name,access,pc_url,private_room,free_drink,"
                    "non_smoking,course,catch,capacity,party_capacity,raw_json,source,"
                    "first_seen_at,last_seen_at,fetched_at) "
                    "VALUES(?,?,'',?,'',?,?,?,'','','','','','','','','','',?,'tokyo',?,?,?)",
                    (sid, name, address, lat, lng, args.dataset_name,
                     raw, now, now, now))
                conn.execute(
                    "INSERT OR IGNORE INTO judgements(shop_id,kaishoku_score,"
                    "instagram_score,enriched_at,ward) VALUES(?,0,0,?,?)",
                    (sid, now, wm.group(1) if wm else ""))
                new_n += 1
        conn.commit()
    print(f"\n=== 完了: 新規{new_n} / 更新{upd_n} / 区外除外{skip} ===",
          file=sys.stderr)


if __name__ == "__main__":
    main()
