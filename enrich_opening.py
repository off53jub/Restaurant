#!/usr/bin/env python3
"""営業時間の構造化（H2、無料・既存raw_jsonから抽出）。

HotPepperの自由形式テキスト「月～金、祝前日: 17:30～21:30 (料理L.O. 21:00)...」と
OSMの opening_hours タグ「Mo-Su 17:00-23:00」を解析して、
ランチ営業有無/ディナー営業有無/深夜営業/L.O.時刻を構造化する。

判定の効果:
  - 「夜デート/接待」で「ランチのみ営業」店を確実に除外
  - 「2次会候補」を「深夜L.O.の店」に絞る
  - 「ランチデート」を「ランチ営業ある店」だけに
"""
import argparse
import datetime as dt
import json
import re
import sys

import db as dbmod


# HotPepper形式: "月～金、祝前日: 11:30～14:30 ... 17:30～21:30 （料理L.O. 21:00 ...）"
HP_LO_RE = re.compile(r"料理\s*L\.O\.\s*(翌?\d{1,2})[:：]?(\d{2})?")
TIME_RE = re.compile(r"(\d{1,2})[:：](\d{2})")
TRANSLATION_TIMES = {"翌": 24}  # 翌1時 → 25時相当


def parse_hp_open(open_text):
    """HotPepperの open フィールドを構造化。"""
    if not open_text:
        return None
    t = open_text
    has_lunch = bool(re.search(r"1[12][:：]\d{2}|11時|12時|10[:：]\d{2}", t))
    has_dinner = bool(re.search(r"1[7-9][:：]\d{2}|2[0-3][:：]\d{2}", t))

    # L.O. 時刻: 「料理L.O. 21:00」「料理L.O. 翌1:00」「料理L.O. 23:30」
    dinner_lo_hour = None
    for m in HP_LO_RE.finditer(t):
        h_text = m.group(1)
        if h_text.startswith("翌"):
            h = int(h_text[1:]) + 24
        else:
            h = int(h_text)
        if h >= 17 or h <= 5:  # 夜のL.O.として
            if dinner_lo_hour is None or h > dinner_lo_hour:
                dinner_lo_hour = h

    # 深夜営業
    late_night = bool(re.search(r"翌|深夜", t))
    if not late_night:
        # 23時以降終わるなら深夜寄り
        for m in re.finditer(r"[～\-~]\s*(\d{1,2})[:：]\d{2}", t):
            try:
                if int(m.group(1)) >= 23:
                    late_night = True
            except ValueError:
                pass

    # 「夜のみ」キーワード
    dinner_only = "夜のみ" in t or (has_dinner and not has_lunch)

    return {
        "source": "hotpepper",
        "has_lunch": has_lunch,
        "has_dinner": has_dinner,
        "dinner_lo_hour": dinner_lo_hour,
        "late_night": late_night,
        "dinner_only": dinner_only,
    }


def parse_osm_opening(text):
    """OSMの opening_hours タグを簡易解析（OSM文法の完全実装はしない）。"""
    if not text:
        return None
    # 例: "Mo-Su 17:00-23:00", "Mo-Fr 11:00-15:00,17:00-23:00"
    times = re.findall(r"(\d{1,2}):\d{2}", text)
    nums = []
    for t in times:
        try:
            nums.append(int(t))
        except ValueError:
            pass
    if not nums:
        return {"source": "osm", "raw": text[:80]}
    has_lunch = any(11 <= n <= 14 for n in nums)
    has_dinner = any(n >= 17 or n <= 5 for n in nums)
    late_night = any(n >= 23 or 0 <= n <= 5 for n in nums)
    # 一番遅い時刻を L.O. 近似に
    dinner_lo_hour = max([n for n in nums if n >= 12], default=None)
    return {
        "source": "osm",
        "has_lunch": has_lunch,
        "has_dinner": has_dinner,
        "dinner_lo_hour": dinner_lo_hour,
        "late_night": late_night,
        "dinner_only": has_dinner and not has_lunch,
    }


def extract(raw_json_str, source):
    try:
        d = json.loads(raw_json_str)
    except (TypeError, ValueError):
        return None
    if source == "hotpepper":
        return parse_hp_open(d.get("open"))
    if source == "osm":
        tags = d.get("tags") or {}
        return parse_osm_opening(tags.get("opening_hours"))
    return None


def main():
    ap = argparse.ArgumentParser(description="営業時間を構造化して judgements に保存")
    ap.add_argument("--db", default="db/shops.db")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--source", choices=["osm", "hotpepper", "all"], default="all")
    args = ap.parse_args()

    conn = dbmod.init_db(args.db)
    where = "1=1"
    if args.source != "all":
        where = f"s.source='{args.source}'"
    sql = f"SELECT s.id, s.source, s.raw_json FROM shops s WHERE {where}"
    if args.limit > 0:
        sql += f" LIMIT {int(args.limit)}"
    rows = list(conn.execute(sql))
    print(f"対象: {len(rows):,}件", file=sys.stderr)

    n_with = 0
    for i, r in enumerate(rows, 1):
        data = extract(r["raw_json"], r["source"])
        if data:
            conn.execute(
                "UPDATE judgements SET opening_hours_json=? WHERE shop_id=?",
                (json.dumps(data, ensure_ascii=False), r["id"]),
            )
            n_with += 1
        if i % 10000 == 0:
            conn.commit()
            print(f"  [{i}/{len(rows)}] 構造化済 {n_with:,}件", file=sys.stderr)
    conn.commit()
    print(f"\n=== 完了: {n_with:,}件 ===", file=sys.stderr)


if __name__ == "__main__":
    main()
