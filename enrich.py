#!/usr/bin/env python3
"""店舗ページを取得して、会食向けの判定情報を抽出。

入力: search.py --save-json で出力したJSON
出力: 条件を満たす候補のテキスト一覧 + enriched JSON

抽出項目:
  - 飲み放題込みコース価格（最安）
  - 完全個室の明記
  - 会食適性キーワード（会食/接待/商談/落ち着いた/静か...）
  - 5〜8名対応の中規模個室の有無
  - 喫煙可否（参考情報、フィルタには使わない）

フィルタ条件（matches_criteria）:
  - 飲み放題込みコースが max_budget 円以下に存在（飲み放題条件は --no-drink-filterで解除）
  - 完全個室と明記
  - 中規模個室対応の明記がある or --any-room で解除
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

# 会食適性: 接待・役員会食向けの表現
KAISHOKU_KEYWORDS = [
    "会食", "接待", "商談", "顔合わせ", "おもてなし",
    "落ち着いた", "落ち着き", "静かな", "上質", "厳かな",
    "大人の", "隠れ家", "VIP",
]

# インスタ映え・フォトジェニック系キーワード
INSTAGRAM_KEYWORDS = [
    "フォトジェニック", "インスタ映え", "SNS映え", "映える",
    "夜景", "絶景", "テラス", "非日常", "おしゃれ",
    "スタイリッシュ", "アート", "ロケーション", "フォト",
    "空間", "内装", "デザイン", "ビュー",
]

# 5〜8名対応の中規模個室
MID_ROOM_PATTERNS = [
    r"[5-8]\s*[名人]様?用?個室",
    r"[5-8]\s*[名人]様?まで",
    r"個室.{0,20}[5-8]\s*[名人]",
    r"[4-6]\s*[名人]\s*[～〜~]\s*[6-9]\s*[名人]",
    r"最大\s*[6-9]\s*[名人]",
    r"中個室",
    r"6名様?個室", r"8名様?個室",
]


@dataclass
class Judgement:
    drink_course_min_yen: Optional[int] = None
    drink_course_prices: list = field(default_factory=list)
    course_min_yen_any: Optional[int] = None  # 飲み放題条件なしのコース最安
    course_prices_any: list = field(default_factory=list)
    fully_private_room: Optional[bool] = None
    smoking_at_seat: Optional[str] = None  # "allowed" | "forbidden" | "partial" | "unknown"
    smoking_evidence: str = ""
    private_evidence: str = ""
    kaishoku_score: int = 0  # 会食キーワードのヒット数
    kaishoku_hits: list = field(default_factory=list)
    mid_room_ok: Optional[bool] = None  # 5-8名個室の明記
    mid_room_evidence: str = ""
    atmosphere_calm: Optional[int] = None   # 0=にぎやか … 100=落ち着いた
    atmosphere_special: Optional[int] = None  # 0=普段使い … 100=特別な日
    instagram_score: int = 0
    instagram_hits: list = field(default_factory=list)
    shop_description: str = ""               # ページ内の「お店の特徴」等
    fetch_error: Optional[str] = None


def fetch(url, timeout=20, retries=2, backoff=1.5):
    """指定URLをGETしてHTMLを返す。失敗時は指数バックオフでリトライ。

    全試行が失敗したら "__ERROR__: ..." 文字列を返す（呼び出し側が判定）。
    一過性のネットワーク不調で店が永続的にエラー扱いになるのを防ぐ。
    """
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt))
    return f"__ERROR__: {type(last_err).__name__}: {last_err}"


def html_to_text(html):
    """HTMLからscript/style除去のテキストを返す。"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.extract()
    return soup.get_text("\n", strip=True)


# 「飲み放題+1,650円」のような追加料金・別途料金を示す直前文字
ADDON_PREFIX_RE = re.compile(r"[+＋]\s*$|別\s*$|追加\s*$|単品\s*$")


def extract_drink_course_prices(text, window=200, min_yen=2500, max_yen=50000):
    """「飲み放題」近傍にある“飲み放題付きコース”価格を抽出。

    誤検出対策:
      - 窓を ±200 に狭め（メニュー単品の巻き込みを抑制）
      - min_yen=2500 で単品ドリンク/飲み放題追加料金(~1500-1980)を除外
      - 価格直前が「+」「別途」「追加」「単品」なら追加料金とみなし除外
    会食/デート用途(5000円〜)では min_yen=2500 でも実コースは取りこぼさない。
    """
    prices = []
    for m in re.finditer("|".join(map(re.escape, DRINK_KEYWORDS)), text):
        start = max(0, m.start() - window)
        end = min(len(text), m.end() + window)
        win = text[start:end]
        for pm in PRICE_RE.finditer(win):
            try:
                yen = int(pm.group(1).replace(",", ""))
            except ValueError:
                continue
            if not (min_yen <= yen <= max_yen):
                continue
            if ADDON_PREFIX_RE.search(win[: pm.start()]):
                continue
            prices.append(yen)
    return sorted(set(prices))


def extract_course_prices_any(text):
    """「コース」の前後300文字以内にある価格を全て抽出（飲み放題条件なし）。"""
    prices = []
    for m in re.finditer("コース", text):
        start = max(0, m.start() - 300)
        end = min(len(text), m.end() + 300)
        window = text[start:end]
        for pm in PRICE_RE.finditer(window):
            try:
                yen = int(pm.group(1).replace(",", ""))
                if 2000 <= yen <= 50000:  # 単品やドリンクは除外
                    prices.append(yen)
            except ValueError:
                continue
    return sorted(set(prices))


def detect_kaishoku(text):
    """会食適性キーワードのヒット数とヒット内容を返す。"""
    hits = []
    for kw in KAISHOKU_KEYWORDS:
        if kw in text:
            hits.append(kw)
    return len(hits), hits


def detect_instagram(text):
    """インスタ映え系キーワードのヒット数とヒット内容を返す。"""
    hits = []
    for kw in INSTAGRAM_KEYWORDS:
        if kw in text:
            hits.append(kw)
    return len(hits), hits


def detect_mid_room(text):
    """5〜8名対応の中規模個室があるかを判定。"""
    for pat in MID_ROOM_PATTERNS:
        m = re.search(pat, text)
        if m:
            return True, m.group(0)
    return None, ""


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


def extract_atmosphere(html):
    """atmosphereWrap の range input から (calm, special) を返す。None は取得失敗。
    calm:    0=にぎやか … 100=落ち着いた
    special: 0=普段使い … 100=特別な日
    """
    if not html or html.startswith("__ERROR__"):
        return None, None
    soup = BeautifulSoup(html, "html.parser")
    wrap = soup.find(class_="atmosphereWrap")
    if not wrap:
        return None, None
    sliders = wrap.find_all("input", {"type": "range"})
    calm = int(sliders[0]["value"]) if len(sliders) > 0 else None
    special = int(sliders[1]["value"]) if len(sliders) > 1 else None
    return calm, special


_MENU_PRICE_RE = re.compile(r"\d[\d,]*\s*円\s*[（(]\s*税込\s*[)）]")
_MULTI_PRICE_RE = re.compile(r"\d[\d,]*\s*円")


def _is_menu_block(text):
    """メニュー説明（「○○円（税込）」、または料金3つ以上）かを判定。"""
    if _MENU_PRICE_RE.search(text):
        return True
    return len(_MULTI_PRICE_RE.findall(text)) >= 3


def extract_shop_description(html, max_chars=600):
    """HotPepperページから店ごとのオリジナル紹介文を抽出。

    column5A クラスに各セクション（個室/コース/外観/料理など）の説明が入っている。
    メニュー＋料金が並ぶブロックは除外し、店の特徴・空間・雰囲気を伝える文だけ拾う。
    """
    if not html or html.startswith("__ERROR__"):
        return ""
    soup = BeautifulSoup(html, "html.parser")
    blocks = []
    for el in soup.find_all(class_="column5A"):
        t = el.get_text(" ", strip=True)
        if not (30 < len(t) < 400):
            continue
        if _is_menu_block(t):
            continue
        # 重複（ほぼ同文）を排除
        if not any(t[:50] == b[:50] for b in blocks):
            blocks.append(t)
    text = " / ".join(blocks)
    return text[:max_chars]


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

    # コース価格（飲み放題込み）
    prices = extract_drink_course_prices(combined)
    j.drink_course_prices = prices
    j.drink_course_min_yen = prices[0] if prices else None

    # コース価格（飲み放題条件なし、参考）
    prices_any = extract_course_prices_any(combined)
    j.course_prices_any = prices_any
    j.course_min_yen_any = prices_any[0] if prices_any else None

    # 完全個室
    fully_private, p_ev = detect_fully_private(combined)
    j.fully_private_room = fully_private
    j.private_evidence = p_ev

    # 喫煙（参考情報）
    smoking, s_ev = detect_smoking(combined)
    j.smoking_at_seat = smoking
    j.smoking_evidence = s_ev

    # 会食適性
    score, hits = detect_kaishoku(combined)
    j.kaishoku_score = score
    j.kaishoku_hits = hits

    # 中規模個室
    mid_ok, mid_ev = detect_mid_room(combined)
    j.mid_room_ok = mid_ok
    j.mid_room_evidence = mid_ev

    # 雰囲気スライダー（トップページのみに存在）
    j.atmosphere_calm, j.atmosphere_special = extract_atmosphere(top_html)

    # インスタ映え
    ig_score, ig_hits = detect_instagram(combined)
    j.instagram_score = ig_score
    j.instagram_hits = ig_hits

    # 店ごとのオリジナル紹介文（HotPepperページ内 column5A）
    j.shop_description = extract_shop_description(top_html)

    return j


def matches_criteria(judgement, max_budget=8800, require_drink=True, require_mid_room=True):
    """最終フィルタ。
    - 価格: require_drink=True なら飲み放題込み、Falseならコース価格で判定
    - 完全個室の明記必須
    - require_mid_room=True なら 5-8名個室の明記が必要
    """
    if judgement.fetch_error:
        return False
    price = judgement.drink_course_min_yen if require_drink else (
        judgement.drink_course_min_yen or judgement.course_min_yen_any
    )
    if price is None:
        return False
    if price > max_budget:
        return False
    if judgement.fully_private_room is not True:
        return False
    if require_mid_room and judgement.mid_room_ok is not True:
        return False
    return True


def format_result(shop, judgement):
    smoke_label = {
        "allowed": "○ 喫煙可",
        "partial": "△ 分煙/喫煙室",
        "unknown": "? 記載なし",
        "forbidden": "× 全面禁煙",
        None: "?",
    }[judgement.smoking_at_seat]
    prices_str = (
        " / ".join(f"{p:,}円" for p in judgement.drink_course_prices[:6])
        if judgement.drink_course_prices
        else "(なし)"
    )
    any_prices_str = (
        " / ".join(f"{p:,}円" for p in judgement.course_prices_any[:6])
        if judgement.course_prices_any
        else "(なし)"
    )
    return (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{shop.get('name', '')}\n"
        f"  ジャンル:   {shop.get('genre', {}).get('name', '')}\n"
        f"  住所:       {shop.get('address', '')}\n"
        f"  アクセス:   {shop.get('access', '')}\n"
        f"  飲み放題込みコース: {prices_str}\n"
        f"  通常コース価格:     {any_prices_str}\n"
        f"  完全個室:   {'○ 明記あり' if judgement.fully_private_room else '? 明記なし'}"
        f"{(' [' + judgement.private_evidence + ']') if judgement.private_evidence else ''}\n"
        f"  5-8名個室:  {'○' if judgement.mid_room_ok else '?'}"
        f"{(' [' + judgement.mid_room_evidence + ']') if judgement.mid_room_evidence else ''}\n"
        f"  会食適性:   スコア{judgement.kaishoku_score}"
        f"{(' [' + ', '.join(judgement.kaishoku_hits[:5]) + ']') if judgement.kaishoku_hits else ''}\n"
        f"  インスタ映え: スコア{judgement.instagram_score}"
        f"{(' [' + ', '.join(judgement.instagram_hits[:5]) + ']') if judgement.instagram_hits else ''}\n"
        f"  雰囲気:     落ち着いた={judgement.atmosphere_calm if judgement.atmosphere_calm is not None else '?'}/100"
        f"  特別な日={judgement.atmosphere_special if judgement.atmosphere_special is not None else '?'}/100\n"
        f"  喫煙:       {smoke_label}"
        f"{(' [' + judgement.smoking_evidence + ']') if judgement.smoking_evidence else ''}\n"
        f"  URL:        {shop.get('urls', {}).get('pc', '')}\n"
    )


def main():
    ap = argparse.ArgumentParser(description="会食向け店舗の判定 (fetch + キーワード抽出)")
    ap.add_argument("--input", required=True, help="search.py --save-json の出力")
    ap.add_argument("--output", help="enriched JSONの保存先（省略可）")
    ap.add_argument("--max-budget", type=int, default=8800)
    ap.add_argument("--max-shops", type=int, default=0, help=">0で先頭N件のみ処理（試走用）")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--delay", type=float, default=0.5, help="同一店舗内のfetch間スリープ秒")
    ap.add_argument("--show-all", action="store_true", help="フィルタ落ちした店も表示")
    ap.add_argument(
        "--no-drink-filter",
        action="store_true",
        help="飲み放題込みコース価格でなく、通常コース価格でフィルタする",
    )
    ap.add_argument(
        "--any-room",
        action="store_true",
        help="5-8名個室の明記がなくても通す（個室の収容人数は問わない）",
    )
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
                f"min={j.drink_course_min_yen} private={j.fully_private_room} "
                f"calm={j.atmosphere_calm} special={j.atmosphere_special} ig={j.instagram_score} smoke={j.smoking_at_seat}",
                file=sys.stderr,
            )

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(enriched, ensure_ascii=False, indent=2))
        print(f"enriched JSON保存: {args.output}", file=sys.stderr)

    require_drink = not args.no_drink_filter
    require_mid_room = not args.any_room
    matched = [
        (e["shop"], Judgement(**e["judgement"]))
        for e in enriched
        if matches_criteria(
            Judgement(**e["judgement"]),
            args.max_budget,
            require_drink=require_drink,
            require_mid_room=require_mid_room,
        )
    ]
    # 会食適性スコア降順 → 価格昇順でソート
    matched.sort(
        key=lambda x: (
            -x[1].kaishoku_score,
            x[1].drink_course_min_yen or x[1].course_min_yen_any or 99999,
        )
    )

    print("\n" + "=" * 60)
    print(f"条件マッチ: {len(matched)}件 / 全{len(enriched)}件")
    print("=" * 60 + "\n")
    for shop, j in matched:
        print(format_result(shop, j))

    if args.show_all:
        unmatched = [
            (e["shop"], Judgement(**e["judgement"]))
            for e in enriched
            if not matches_criteria(
                Judgement(**e["judgement"]),
                args.max_budget,
                require_drink=require_drink,
                require_mid_room=require_mid_room,
            )
        ]
        print("\n" + "=" * 60)
        print(f"フィルタ落ち: {len(unmatched)}件")
        print("=" * 60 + "\n")
        for shop, j in unmatched:
            reason = []
            if j.fetch_error:
                reason.append(f"fetch失敗:{j.fetch_error[:40]}")
            check_price = j.drink_course_min_yen if require_drink else (
                j.drink_course_min_yen or j.course_min_yen_any
            )
            if check_price is None:
                reason.append("コース価格抽出失敗")
            elif check_price > args.max_budget:
                reason.append(f"最安{check_price}円>{args.max_budget}")
            if j.fully_private_room is not True:
                reason.append("完全個室の明記なし")
            if require_mid_room and j.mid_room_ok is not True:
                reason.append("5-8名個室の明記なし")
            print(f"  - {shop.get('name', '')[:40]}: {', '.join(reason)}")

    print(
        "\n注意: 価格・個室収容人数・営業状況は最終的に店舗ページと電話で確認してください。",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
