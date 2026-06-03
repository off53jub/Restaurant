#!/usr/bin/env python3
"""店の口コミを取り出して「こういう口コミがあった」形式で表示。

ソース: 現状は google_enrich.py --with-reviews で取得した reviews テーブル。
要約: LLM APIを使わない簡易版（テーマキーワード集計＋代表口コミ抽出）。

例:
  python reviews.py --shop-id J003559227
  python reviews.py --shop-id J003559227 --themes-only
  python reviews.py --area 赤坂 --rating-min 4 --limit 5
"""
import argparse
import re
from collections import Counter

import db as dbmod


# 飲食店レビューでよく出るテーマ語と日本語ラベル
THEME_KEYWORDS = {
    "料理の質": ["美味し", "おいし", "うまい", "絶品", "繊細", "丁寧", "新鮮", "出来立て",
               "本格", "クオリティ", "味付け", "風味", "出汁", "ジューシー"],
    "ボリューム": ["ボリューム", "量が多い", "お腹", "満腹", "コスパ", "リーズナブル", "高い", "高め"],
    "雰囲気": ["雰囲気", "落ち着", "静か", "賑やか", "おしゃれ", "デート", "個室", "カウンター",
             "席", "店内", "内装", "BGM"],
    "接客": ["接客", "サービス", "店員", "スタッフ", "丁寧", "気配り", "対応", "笑顔", "親切"],
    "立地・利便性": ["駅近", "便利", "アクセス", "立地", "わかりやすい", "わかりにく", "迷"],
    "予約・混雑": ["予約", "並ぶ", "混", "空い", "待ち", "満席", "穴場"],
    "シーン適合": ["接待", "会食", "デート", "記念日", "家族", "一人", "女子会", "飲み会"],
    "禁煙・喫煙": ["禁煙", "喫煙", "タバコ", "煙"],
}


def extract_themes(texts):
    """口コミテキスト群から、ヒットしたテーマキーワードをカテゴリ別に集計。"""
    hits = Counter()
    examples = {}
    for text in texts:
        for category, kws in THEME_KEYWORDS.items():
            for kw in kws:
                if kw in text:
                    hits[category] += 1
                    if category not in examples:
                        # キーワード前後30字を例示として
                        idx = text.find(kw)
                        start = max(0, idx - 20)
                        end = min(len(text), idx + len(kw) + 30)
                        examples[category] = text[start:end].replace("\n", " ")
                    break  # 同カテゴリは1テキストにつき1回まで
    return hits, examples


def pick_representative(reviews, k=3):
    """要約代わりに、代表的な3件を選ぶ（★高+低+中庸 or 文字数バランス）。"""
    if not reviews:
        return []
    # 文字数 30 以上のものに絞る
    valid = [r for r in reviews if r["text"] and len(r["text"]) >= 30]
    if not valid:
        valid = reviews
    # 高評価1件 + 中評価1件 + 低評価1件 を狙う
    by_rating = sorted(valid, key=lambda x: -(x["rating"] or 0))
    picks = []
    if by_rating:
        picks.append(by_rating[0])  # 高評価
    if len(by_rating) >= 2:
        picks.append(by_rating[-1])  # 低評価
    if len(by_rating) >= 3:
        picks.append(by_rating[len(by_rating) // 2])  # 中評価
    return picks[:k]


def fetch_reviews(conn, shop_id):
    return list(conn.execute(
        "SELECT * FROM reviews WHERE shop_id=? ORDER BY rating DESC, length(text) DESC",
        (shop_id,),
    ))


def fetch_shops_by_area(conn, areas, rating_min=None, limit=10):
    where = ["EXISTS (SELECT 1 FROM reviews r WHERE r.shop_id=s.id)"]
    params = []
    if areas:
        ors = " OR ".join("s.address LIKE ?" for _ in areas)
        where.append(f"({ors})")
        params.extend(f"%{a}%" for a in areas)
    if rating_min is not None:
        where.append(
            "EXISTS (SELECT 1 FROM google g WHERE g.shop_id=s.id AND g.rating >= ?)"
        )
        params.append(rating_min)
    sql = f"""
    SELECT s.id, s.name, s.address,
           g.rating AS google_rating, g.user_ratings_total AS google_reviews
    FROM shops s LEFT JOIN google g ON g.shop_id=s.id
    WHERE {' AND '.join(where)}
    ORDER BY g.user_ratings_total DESC NULLS LAST
    LIMIT ?
    """
    params.append(limit)
    return list(conn.execute(sql, params))


def format_shop_section(shop, reviews, themes_only=False):
    out = []
    head = f"\n■ {shop['name']}"
    if shop.get("google_rating"):
        head += f"  Google★{shop['google_rating']} ({shop.get('google_reviews', 0)}件)"
    out.append(head)
    out.append(f"  住所: {shop.get('address','')}")
    if not reviews:
        out.append("  （口コミデータなし）")
        return "\n".join(out)

    # テーマ集計
    texts = [r["text"] for r in reviews if r["text"]]
    hits, examples = extract_themes(texts)
    out.append(f"  口コミ {len(reviews)}件のテーマ集計:")
    for category, count in hits.most_common(8):
        ex = examples.get(category, "")
        out.append(f"    ▸ {category} ({count}件) — 例: 「…{ex}…」" if ex
                   else f"    ▸ {category} ({count}件)")
    if themes_only:
        return "\n".join(out)

    # 代表口コミ
    out.append("\n  代表的な口コミ:")
    for rv in pick_representative(reviews, 3):
        star = "★" * int(rv["rating"] or 0)
        author = rv["author"] or "(匿名)"
        when = rv["relative_time"] or ""
        body = (rv["text"] or "").replace("\n", " ")[:200]
        out.append(f"    {star} {author} {when}")
        out.append(f"    「{body}{'…' if len(rv['text'] or '') > 200 else ''}」")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="店の口コミ要約 (Googleレビューベース)")
    ap.add_argument("--db", default="db/shops.db")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--shop-id", help="特定店のID")
    src.add_argument("--area", action="append", help="エリア指定（複数可）")
    ap.add_argument("--rating-min", type=float)
    ap.add_argument("--limit", type=int, default=5, help="エリア指定時の店舗上限")
    ap.add_argument("--themes-only", action="store_true",
                    help="代表口コミ本文は出さずテーマ集計のみ")
    args = ap.parse_args()

    conn = dbmod.connect(args.db)
    if args.shop_id:
        shop = conn.execute(
            "SELECT s.id, s.name, s.address, g.rating AS google_rating, "
            "g.user_ratings_total AS google_reviews "
            "FROM shops s LEFT JOIN google g ON g.shop_id=s.id WHERE s.id=?",
            (args.shop_id,),
        ).fetchone()
        if not shop:
            raise SystemExit(f"shop_id {args.shop_id} がDBに無い")
        shops = [shop]
    else:
        shops = fetch_shops_by_area(conn, args.area, args.rating_min, args.limit)

    if not shops:
        print("対象店なし。先に `google_enrich.py --with-reviews` で口コミを取得してください。")
        return

    for shop in shops:
        reviews = fetch_reviews(conn, shop["id"])
        print(format_shop_section(dict(shop), reviews, args.themes_only))


if __name__ == "__main__":
    main()
