#!/usr/bin/env python3
"""虎ノ門エリアの飲食店検索CLI。ホットペッパーグルメAPIを利用。

条件:
  - 指定座標から半径2km
  - 個室あり
  - 飲み放題あり
  - 予算8800円以下（ディナー平均予算ベース、後段でコース確認推奨）
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://webservice.recruit.co.jp/hotpepper/gourmet/v1/"

TORANOMON_LAT = 35.6677
TORANOMON_LNG = 139.7497

RANGE_LABEL = {1: "300m", 2: "500m", 3: "1km", 4: "2km", 5: "3km"}


def fetch_all(api_key, lat, lng, range_code):
    """ページングしながら全件取得。"""
    shops = []
    start = 1
    count = 100
    while True:
        params = {
            "key": api_key,
            "lat": lat,
            "lng": lng,
            "range": range_code,
            "private_room": 1,
            "free_drink": 1,
            "count": count,
            "start": start,
            "format": "json",
        }
        resp = requests.get(API_URL, params=params, timeout=30)
        resp.raise_for_status()
        results = resp.json().get("results", {})
        page = results.get("shop", [])
        shops.extend(page)
        total = int(results.get("results_available", 0))
        print(
            f"  page start={start}: {len(page)}件取得 (累計{len(shops)}/{total})",
            file=sys.stderr,
        )
        if start + count > total or not page:
            break
        start += count
        time.sleep(0.3)
    return shops


def budget_lower_yen(shop):
    """ディナー平均予算の下限を円で返す。不明はNone。"""
    name = shop.get("budget", {}).get("name", "")
    m = re.search(r"([\d,]+)", name)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def filter_by_budget(shops, max_yen):
    """ディナー平均予算が max_yen 以下のものに絞る。不明は残す。"""
    out = []
    for s in shops:
        low = budget_lower_yen(s)
        if low is None or low <= max_yen:
            out.append(s)
    return out


def format_shop(s):
    g = lambda k, default="": s.get(k, default) or default
    pc = s.get("urls", {}).get("pc", "")
    return (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{g('name')}\n"
        f"  ジャンル: {s.get('genre', {}).get('name', '')}\n"
        f"  住所:     {g('address')}\n"
        f"  アクセス: {g('access')}\n"
        f"  予算:     {s.get('budget', {}).get('name', '')}"
        f"{(' / ' + g('budget_memo')) if g('budget_memo') else ''}\n"
        f"  個室:     {g('private_room')}\n"
        f"  飲み放題: {g('free_drink')}\n"
        f"  禁煙席:   {g('non_smoking')}\n"
        f"  コース:   {g('course')}\n"
        f"  URL:      {pc}\n"
    )


def main():
    ap = argparse.ArgumentParser(description="虎ノ門2km圏 個室＋飲み放題 レストラン検索")
    ap.add_argument("--lat", type=float, default=TORANOMON_LAT)
    ap.add_argument("--lng", type=float, default=TORANOMON_LNG)
    ap.add_argument(
        "--range",
        type=int,
        default=4,
        choices=[1, 2, 3, 4, 5],
        help="1=300m 2=500m 3=1km 4=2km 5=3km (default: 4)",
    )
    ap.add_argument("--max-budget", type=int, default=8800, help="円 (default: 8800)")
    ap.add_argument("--save-json", type=str, help="生レスポンスをJSON保存")
    ap.add_argument("--format", choices=["text", "json", "tsv"], default="text")
    args = ap.parse_args()

    api_key = os.environ.get("HOTPEPPER_API_KEY")
    if not api_key:
        print("ERROR: HOTPEPPER_API_KEY が .env に設定されていません", file=sys.stderr)
        sys.exit(1)

    print(
        f"検索: ({args.lat}, {args.lng}) 半径{RANGE_LABEL[args.range]} / "
        f"個室・飲み放題あり / 予算{args.max_budget}円以下",
        file=sys.stderr,
    )
    shops = fetch_all(api_key, args.lat, args.lng, args.range)
    print(f"API取得合計: {len(shops)}件", file=sys.stderr)

    if args.save_json:
        Path(args.save_json).write_text(
            json.dumps(shops, ensure_ascii=False, indent=2)
        )
        print(f"生JSON保存: {args.save_json}", file=sys.stderr)

    filtered = filter_by_budget(shops, args.max_budget)
    print(f"予算絞込後: {len(filtered)}件", file=sys.stderr)

    if args.format == "json":
        print(json.dumps(filtered, ensure_ascii=False, indent=2))
    elif args.format == "tsv":
        print("name\tgenre\taddress\tbudget\tprivate_room\tfree_drink\tnon_smoking\turl")
        for s in filtered:
            print(
                "\t".join(
                    [
                        s.get("name", ""),
                        s.get("genre", {}).get("name", ""),
                        s.get("address", ""),
                        s.get("budget", {}).get("name", ""),
                        s.get("private_room", ""),
                        s.get("free_drink", ""),
                        s.get("non_smoking", ""),
                        s.get("urls", {}).get("pc", ""),
                    ]
                )
            )
    else:
        for s in filtered:
            print(format_shop(s))
        print(
            f"\n合計 {len(filtered)} 件 "
            f"(半径{RANGE_LABEL[args.range]}・個室・飲み放題・予算{args.max_budget}円以下)",
            file=sys.stderr,
        )
        print(
            "\n注意: 「席で喫煙可」「完全個室」「飲み放題込みコース8800円以下」は\n"
            "APIだけでは確定できません。各店のURLでコース内容と喫煙可否を確認してください。",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
