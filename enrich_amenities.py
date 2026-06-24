#!/usr/bin/env python3
"""OSM raw_json の amenity 系タグを judgements.amenities_json に展開（G4）。

OSMのraw_jsonに既にある wheelchair/takeaway/outdoor_seating/payment 等を
構造化してDBに出し、query.pyでフィルタ可能にする。
HotPepper店にも non_smoking など同等情報があれば取り込む。
"""
import argparse
import datetime as dt
import json
import sys

import db as dbmod


AMENITY_KEYS = [
    "wheelchair",            # バリアフリー
    "takeaway",              # テイクアウト
    "delivery",              # デリバリー
    "outdoor_seating",       # テラス席
    "smoking",               # 喫煙ルール
    "internet_access",       # Wi-Fi/ネット
    "payment:credit_cards",  # クレカ
    "payment:debit_cards",   # デビット
    "payment:cash",          # 現金
    "payment:visa",
    "payment:mastercard",
    "payment:amex",
    "payment:jcb",
    "payment:american_express",
    "payment:apple_pay",
    "payment:google_pay",
    "payment:wechat",
    "payment:line_pay",
    "payment:paypay",
    "diet:vegetarian",
    "diet:vegan",
    "diet:halal",
    "diet:kosher",
    "diet:gluten_free",
    "reservation",           # 要予約か
    "level",                 # 階数
    "indoor_seating",
    "drink:sake",
    "drink:wine",
    "drink:beer",
]


def extract_osm_amenities(raw_json_str):
    """OSM raw_json から amenity 系タグを抽出して dict に。"""
    try:
        tags = (json.loads(raw_json_str).get("tags") or {})
    except (TypeError, ValueError):
        return {}
    out = {}
    for k in AMENITY_KEYS:
        v = tags.get(k)
        if v is not None and v != "":
            # 'yes'/'no'/'limited' などの yes/no は boolean に
            if isinstance(v, str) and v.lower() in ("yes", "true"):
                out[k] = True
            elif isinstance(v, str) and v.lower() in ("no", "false"):
                out[k] = False
            else:
                out[k] = v
    return out


def extract_hotpepper_amenities(raw_json_str):
    """HotPepper API応答から amenity 相当の情報を集約。"""
    try:
        s = json.loads(raw_json_str)
    except (TypeError, ValueError):
        return {}
    out = {}
    # 「あり」/「なし」/「○○名」のテキスト判定
    POSITIVE = ("あり", "○", "可", "利用可", "ＯＫ", "OK", "全席禁煙",
                "店内全面禁煙", "完全分煙", "全面禁煙")
    NEGATIVE = ("なし", "×", "不可", "ご利用不可", "利用不可")
    def yesno(field):
        v = s.get(field) or ""
        v = v.strip()
        if not v:
            return None
        if v in POSITIVE:
            return True
        if v in NEGATIVE:
            return False
        # 「主要カード」「VISA、JCB等」のような具体的カード列挙は利用可とみなす
        if "VISA" in v or "JCB" in v or "Master" in v or "AMEX" in v or "主要" in v:
            return True
        # 「全席禁煙」「分煙」を含む = non_smoking
        if "禁煙" in v or "分煙" in v:
            return True
        if "喫煙可" in v:
            return False
        return v
    # OSM側のキー名に揃える（query.pyのフィルタが両ソース共通で効くように）
    for f, key in [
        ("private_room", "private_room"),
        ("horigotatsu", "horigotatsu"),
        ("tatami", "tatami"),
        ("non_smoking", "non_smoking"),
        ("card", "payment:credit_cards"),     # OSM互換
        ("free_drink", "free_drink"),
        ("free_food", "free_food"),
        ("charter", "charter"),
        ("parking", "parking"),
        ("barrier_free", "wheelchair"),
        ("wifi", "internet_access"),          # OSM互換
        ("english", "english_menu"),
        ("midnight", "midnight"),
        ("lunch", "lunch"),
        ("pet", "pet_ok"),
        ("child", "child_ok"),
    ]:
        v = yesno(f)
        if v is not None and v != "":
            out[key] = v
    return out


def main():
    ap = argparse.ArgumentParser(description="raw_json から amenity 情報を judgements に展開")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--source", choices=["osm", "hotpepper", "all"], default="all")
    args = ap.parse_args()

    conn = dbmod.init_db(args.db)
    where = "1=1"
    if args.source != "all":
        where = f"s.source = '{args.source}'"
    sql = f"SELECT s.id, s.source, s.raw_json FROM shops s WHERE {where}"
    if args.limit > 0:
        sql += f" LIMIT {int(args.limit)}"
    rows = list(conn.execute(sql))
    print(f"対象: {len(rows):,}件", file=sys.stderr)

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    n_with = 0
    for i, r in enumerate(rows, 1):
        if r["source"] == "osm":
            am = extract_osm_amenities(r["raw_json"])
        elif r["source"] == "hotpepper":
            am = extract_hotpepper_amenities(r["raw_json"])
        else:
            am = {}
        if not am:
            continue
        conn.execute(
            "UPDATE judgements SET amenities_json=? WHERE shop_id=?",
            (json.dumps(am, ensure_ascii=False), r["id"]),
        )
        n_with += 1
        if i % 5000 == 0:
            conn.commit()
            print(f"  [{i}/{len(rows)}] 設備情報あり {n_with:,}件", file=sys.stderr)
    conn.commit()
    print(f"\n=== 完了: {n_with:,}件に amenity 情報を展開 ===", file=sys.stderr)


if __name__ == "__main__":
    main()
