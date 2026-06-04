#!/usr/bin/env python3
"""厚労省 食品衛生申請等システム(FOODS) のオープンデータCSVを読み込みDB保存（H1）。

FOODSのオープンデータは都道府県別の大きなCSV/ZIPとして配布される（手動DL）。
  配布元: 食品衛生申請等システム オープンデータ
  例: 営業許可・届出の一覧（業者名・施設所在地・業種・許可日 等）

ダウンロードしたCSVを --csv で渡す。23区の「飲食店営業」に絞ってUPSERTする。
店名・住所のみ（評価/写真メタは無い）が、HotPepper/OSM未掲載の網羅性を補う。

使い方:
  python ingest_foods.py --csv ~/Downloads/tokyo_foods.csv
  python ingest_foods.py --csv data/foods.csv --encoding cp932
"""
import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

import db as dbmod

ID_PREFIX = "foods:"

WARD_RE = re.compile(
    r"(千代田区|中央区|港区|新宿区|文京区|台東区|墨田区|江東区|品川区|目黒区|"
    r"大田区|世田谷区|渋谷区|中野区|杉並区|豊島区|北区|荒川区|板橋区|練馬区|"
    r"足立区|葛飾区|江戸川区)"
)

# CSVのヘッダ表記ゆれを吸収（FOODSの列名は版により異なる）
COLUMN_ALIASES = {
    "name": ["業者名", "営業者氏名", "施設名称", "屋号", "営業所名称", "名称"],
    "address": ["施設所在地", "営業所所在地", "所在地", "住所"],
    "biz_type": ["業種", "営業の種類", "許可業種", "業種名"],
    "permit_no": ["許可番号", "受付番号", "整理番号"],
    "permit_date": ["許可年月日", "許可日", "申請年月日"],
}

# 飲食店として扱う業種キーワード
FOOD_BIZ_KEYWORDS = ["飲食店営業", "喫茶店営業", "飲食店"]


def resolve_columns(header):
    """ヘッダ行から各論理カラムの実列名を解決。"""
    mapping = {}
    for logical, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            for h in header:
                if a in h:
                    mapping[logical] = h
                    break
            if logical in mapping:
                break
    return mapping


def normalize(row, cols):
    name = (row.get(cols.get("name", "")) or "").strip()
    address = (row.get(cols.get("address", "")) or "").strip()
    biz = (row.get(cols.get("biz_type", "")) or "").strip()
    permit_no = (row.get(cols.get("permit_no", "")) or "").strip()
    permit_date = (row.get(cols.get("permit_date", "")) or "").strip()
    return name, address, biz, permit_no, permit_date


def main():
    ap = argparse.ArgumentParser(description="FOODSオープンデータCSVをDBに取込")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--csv", required=True, help="ダウンロード済みFOODS CSVのパス")
    ap.add_argument("--encoding", default="utf-8-sig",
                    help="CSVの文字コード（cp932/shift_jisのことも）")
    ap.add_argument("--wards-only", action="store_true", default=True,
                    help="東京23区の住所だけ取込（既定ON）")
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
        cols = resolve_columns(header)
        if "name" not in cols or "address" not in cols:
            raise SystemExit(
                f"店名/住所の列を特定できません。ヘッダ: {header}\n"
                f"解決結果: {cols}\n--encoding を変えるか列名を確認してください。")
        print(f"列マッピング: {cols}", file=sys.stderr)

        new_n = upd_n = skip_food = skip_ward = 0
        seen = 0
        for row in reader:
            seen += 1
            if args.limit and seen > args.limit:
                break
            name, address, biz, permit_no, permit_date = normalize(row, cols)
            if not name or not address:
                continue
            # 飲食店業種に限定
            if cols.get("biz_type") and biz and not any(k in biz for k in FOOD_BIZ_KEYWORDS):
                skip_food += 1
                continue
            # 23区限定
            wm = WARD_RE.search(address)
            if args.wards_only and not wm:
                skip_ward += 1
                continue
            # 安定IDを生成（許可番号 or 名前+住所ハッシュ）
            key = permit_no or f"{name}_{address}"
            sid = ID_PREFIX + re.sub(r"\s+", "", key)[:60]
            raw = json.dumps({
                "name": name, "address": address, "biz_type": biz,
                "permit_no": permit_no, "permit_date": permit_date,
            }, ensure_ascii=False)
            row_exist = conn.execute("SELECT raw_json FROM shops WHERE id=?", (sid,)).fetchone()
            if row_exist:
                if row_exist["raw_json"] != raw:
                    conn.execute(
                        "UPDATE shops SET name=?, address=?, genre_name=?, raw_json=?, "
                        "last_seen_at=?, fetched_at=? WHERE id=?",
                        (name, address, biz or "飲食店", raw, now, now, sid))
                    upd_n += 1
                else:
                    conn.execute("UPDATE shops SET last_seen_at=? WHERE id=?", (now, sid))
            else:
                conn.execute(
                    "INSERT INTO shops(id,name,name_kana,address,station_name,lat,lng,"
                    "genre_name,budget_name,access,pc_url,private_room,free_drink,"
                    "non_smoking,course,catch,capacity,party_capacity,raw_json,source,"
                    "first_seen_at,last_seen_at,fetched_at) "
                    "VALUES(?,?,'',?,'',NULL,NULL,?,'','','','','','','','','','',?,'foods',?,?,?)",
                    (sid, name, address, biz or "飲食店", raw, now, now, now))
                conn.execute(
                    "INSERT OR IGNORE INTO judgements(shop_id,kaishoku_score,"
                    "instagram_score,enriched_at,ward) VALUES(?,0,0,?,?)",
                    (sid, now, wm.group(1) if wm else ""))
                new_n += 1
            if (new_n + upd_n) % 1000 == 0:
                conn.commit()
                print(f"  取込 新規{new_n}/更新{upd_n} (非飲食除外{skip_food}/区外{skip_ward})",
                      file=sys.stderr)
        conn.commit()

    total_foods = conn.execute("SELECT COUNT(*) FROM shops WHERE source='foods'").fetchone()[0]
    total_all = conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0]
    print(f"\n=== FOODS取込完了 ===\n"
          f"  新規{new_n} / 更新{upd_n} / 非飲食除外{skip_food} / 区外除外{skip_ward}\n"
          f"  FOODS店総数: {total_foods:,} / 全体DB: {total_all:,}", file=sys.stderr)


if __name__ == "__main__":
    main()
