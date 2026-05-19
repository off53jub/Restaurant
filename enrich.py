#!/usr/bin/env python3
"""店舗ページを取得して、コース価格・完全個室・喫煙可否を正規表現とキーワードで抽出。

入力: search.py --save-json で出力したJSON
出力: 条件を満たす候補のテキスト一覧 + enriched JSON

条件:
  - 飲み放題込みコース 8800円以下が存在
  - 完全個室と明記 (半個室・襖は除外)
  - 席で喫煙可（明示的な禁煙でない）
"""
import argparse
import concurrent.futures
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (compatible; RestaurantFilter/0.1; personal-use; "
    "+https://example.local/restaurant-filter)"
)

PRICE_RE = re.compile(r"([\d,]+)\s*円")
DRINK_KEYWORDS = ["飲み放題付", "飲み放題込", "飲み放題あり", "飲み放題"]

SMOKING_ALLOWED_HINTS = [
    "喫煙可",
    "喫煙席あり",
    "全席喫煙",
    "完全喫煙",
    "シガー",
    "加熱式タバコ専用",
    "喫煙目的",
]
SMOKING_FORBIDDEN_HINTS = [
    "全席禁煙",
    "全面禁煙",
    "店内禁煙",
    "禁煙のみ",
]
SMOKING_PARTIAL_HINTS = [
    "分煙",
    "完全分煙",
    "禁煙席あり",
    "喫煙ルーム",
    "喫煙スペース",
]

FULLY_PRIVATE_HINT = "完全個室"
SEMI_PRIVATE_HINTS = ["半個室", "半個室あり"]


@dataclass
class Judgement:
    drink_course_min_yen: Optional[int] = None
    drink_course_prices: list = field(default_factory=list)
    fully_private_room: Optional[bool] = None
    smoking_at_seat: Optional[str] = None  # "allowed" | "forbidden" | "partial" | "unknown"
    smoking_evidence: str = ""
    private_evidence: str = ""
    fetch_error: Optional[str] = None


def fetch(url, timeout=20):
    """指定URLをGETしてHTMLを返す。失敗時はNone。"""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        return f"__ERROR__: {type(e).__name__}: {e}"


def html_to_text(html):
    """HTMLからscript/style除去のテキストを返す。"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.extract()
    return soup.get_text("\n", strip=True)


def extract_drink_course_prices(text):
    """テキスト中で「飲み放題」の前後500文字以内にある価格を全て抽出。"""
    prices = []
    for m in re.finditer("|".join(map(re.escape, DRINK_KEYWORDS)), text):
        start = max(0, m.start() - 500)
        end = min(len(text), m.end() + 500)
        window = text[start:end]
        for pm in PRICE_RE.finditer(window):
            try:
                yen = int(pm.group(1).replace(",", ""))
                if 500 <= yen <= 50000:  # ありえない値を除外
                    prices.append(yen)
            except ValueError:
                continue
    return sorted(set(prices))


def detect_smoking(text):
    """喫煙可否を判定。優先度: 喫煙可 > 禁煙 > 分煙 > 不明。"""
    for kw in SMOKING_ALLOWED_HINTS:
        if kw in text:
            return "allowed", kw
    for kw in SMOKING_FORBIDDEN_HINTS:
        if kw in text:
            return "forbidden", kw
    for kw in SMOKING_PARTIAL_HINTS:
        if kw in text:
            return "partial", kw
    return "unknown", ""


def detect_fully_private(text):
    """完全個室かを判定。"""
    if FULLY_PRIVATE_HINT in text:
        return True, FULLY_PRIVATE_HINT
    for kw in SEMI_PRIVATE_HINTS:
        if kw in text:
            return False, kw
    return None, ""


def judge_shop(shop, delay=0.5):
    """1店舗の判定を行う。"""
    pc_url = shop.get("urls", {}).get("pc", "")
    j = Judgement()
    if not pc_url:
        j.fetch_error = "no pc_url"
        return j

    top_html = fetch(pc_url)
    time.sleep(delay)
    course_url = pc_url.rstrip("/") + "/course/"
    course_html = fetch(course_url)
    time.sleep(delay)

    if isinstance(top_html, str) and top_html.startswith("__ERROR__"):
        j.fetch_error = top_html
        return j

    top_text = html_to_text(top_html)
    course_text = html_to_text(
        course_html
        if isinstance(course_html, str) and not course_html.startswith("__ERROR__")
        else ""
    )
    combined = top_text + "\n\n" + course_text

    # コース価格
    prices = extract_drink_course_prices(combined)
    j.drink_course_prices = prices
    j.drink_course_min_yen = prices[0] if prices else None

    # 完全個室
    fully_private, p_ev = detect_fully_private(combined)
    j.fully_private_room = fully_private
    j.private_evidence = p_ev

    # 喫煙
    smoking, s_ev = detect_smoking(combined)
    j.smoking_at_seat = smoking
    j.smoking_evidence = s_ev

    return j


def matches_criteria(judgement, max_budget=8800):
    """最終フィルタ。8800円以下＆完全個室＝True＆喫煙=allowed/partial/unknown。"""
    if judgement.fetch_error:
        return False
    if judgement.drink_course_min_yen is None:
        return False
    if judgement.drink_course_min_yen > max_budget:
        return False
    if judgement.fully_private_room is not True:
        return False
    if judgement.smoking_at_seat == "forbidden":
        return False
    return True


def format_result(shop, judgement):
    smoke_label = {
        "allowed": "○ 喫煙可",
        "partial": "△ 分煙/喫煙室",
        "unknown": "? 記載なし(要確認)",
        "forbidden": "× 全面禁煙",
        None: "?",
    }[judgement.smoking_at_seat]
    prices_str = (
        " / ".join(f"{p:,}円" for p in judgement.drink_course_prices[:6])
        if judgement.drink_course_prices
        else "(なし)"
    )
    return (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{shop.get('name', '')}\n"
        f"  ジャンル:   {shop.get('genre', {}).get('name', '')}\n"
        f"  住所:       {shop.get('address', '')}\n"
        f"  アクセス:   {shop.get('access', '')}\n"
        f"  飲み放題込みコース価格候補: {prices_str}\n"
        f"  完全個室:   {'○ 明記あり' if judgement.fully_private_room else '? 明記なし'}"
        f"{(' [' + judgement.private_evidence + ']') if judgement.private_evidence else ''}\n"
        f"  喫煙:       {smoke_label}"
        f"{(' [' + judgement.smoking_evidence + ']') if judgement.smoking_evidence else ''}\n"
        f"  URL:        {shop.get('urls', {}).get('pc', '')}\n"
    )


def main():
    ap = argparse.ArgumentParser(description="店舗ページfetch + コース・個室・喫煙抽出")
    ap.add_argument("--input", required=True, help="search.py --save-json の出力")
    ap.add_argument("--output", help="enriched JSONの保存先（省略可）")
    ap.add_argument("--max-budget", type=int, default=8800)
    ap.add_argument("--max-shops", type=int, default=0, help=">0で先頭N件のみ処理（試走用）")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--delay", type=float, default=0.5, help="同一店舗内のfetch間スリープ秒")
    ap.add_argument("--show-all", action="store_true", help="フィルタ落ちした店も表示")
    args = ap.parse_args()

    shops = json.loads(Path(args.input).read_text())
    if args.max_shops > 0:
        shops = shops[: args.max_shops]
    print(f"対象: {len(shops)}件", file=sys.stderr)

    enriched = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = {
            ex.submit(judge_shop, s, args.delay): (i, s) for i, s in enumerate(shops)
        }
        for fut in concurrent.futures.as_completed(futures):
            i, s = futures[fut]
            try:
                j = fut.result()
            except Exception as e:
                j = Judgement(fetch_error=f"{type(e).__name__}: {e}")
            enriched.append({"shop": s, "judgement": asdict(j)})
            print(
                f"  [{len(enriched)}/{len(shops)}] {s.get('name', '')[:30]} "
                f"min={j.drink_course_min_yen} private={j.fully_private_room} smoke={j.smoking_at_seat}",
                file=sys.stderr,
            )

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(enriched, ensure_ascii=False, indent=2))
        print(f"enriched JSON保存: {args.output}", file=sys.stderr)

    matched = [
        (e["shop"], Judgement(**e["judgement"]))
        for e in enriched
        if matches_criteria(Judgement(**e["judgement"]), args.max_budget)
    ]
    matched.sort(key=lambda x: x[1].drink_course_min_yen or 99999)

    print("\n" + "=" * 60)
    print(f"条件マッチ: {len(matched)}件 / 全{len(enriched)}件")
    print("=" * 60 + "\n")
    for shop, j in matched:
        print(format_result(shop, j))

    if args.show_all:
        unmatched = [
            (e["shop"], Judgement(**e["judgement"]))
            for e in enriched
            if not matches_criteria(Judgement(**e["judgement"]), args.max_budget)
        ]
        print("\n" + "=" * 60)
        print(f"フィルタ落ち: {len(unmatched)}件")
        print("=" * 60 + "\n")
        for shop, j in unmatched:
            reason = []
            if j.fetch_error:
                reason.append(f"fetch失敗:{j.fetch_error[:40]}")
            elif j.drink_course_min_yen is None:
                reason.append("飲み放題コース価格抽出失敗")
            elif j.drink_course_min_yen > args.max_budget:
                reason.append(f"最安{j.drink_course_min_yen}円>{args.max_budget}")
            if j.fully_private_room is not True:
                reason.append("完全個室の明記なし")
            if j.smoking_at_seat == "forbidden":
                reason.append(f"禁煙[{j.smoking_evidence}]")
            print(f"  - {shop.get('name', '')[:40]}: {', '.join(reason)}")

    print(
        "\n注意: 「席で喫煙可」は法令上店舗確認が必須です。"
        "「○ 喫煙可」「△ 分煙」表示の店もコース内容と合わせて電話確認推奨。",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
