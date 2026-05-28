# Restaurant Filter

虎ノ門エリア（タクシー10分相当=半径3km）で「会食向け（個室・8800円以下・5〜8名対応）」のレストランを探すCLIツール。

2段階処理：
1. **search.py** — ホットペッパーAPIで一次取得（個室・飲み放題・エリア・予算でフィルタ）
2. **enrich.py** — 各店のページを取得して、コース価格・完全個室・5〜8名個室・会食適性キーワードを抽出

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env を編集して HOTPEPPER_API_KEY を実際のキーに置換
```

APIキーは [リクルートWebサービス](https://webservice.recruit.co.jp/register/) で無料登録すると即時発行されます。

## 使い方（会食リストを作る一気通貫）

```bash
mkdir -p output

# Step 1: ホットペッパーAPIで候補取得（虎ノ門3km / 個室 / 飲み放題 / 8800円以下）
python3 search.py --save-json output/shops.json --format tsv > output/shops.tsv

# Step 2: 各店のページをfetchしてコース・個室・会食適性を抽出
python3 enrich.py --input output/shops.json --output output/enriched.json
```

## 個別オプション

### search.py

```bash
python3 search.py                            # 虎ノ門3km/個室/飲み放題/8800円以下
python3 search.py --range 4                  # 半径2kmに狭める
python3 search.py --no-free-drink            # 飲み放題条件を外す（コース＋単品ワインの会食向け）
python3 search.py --lat 35.6663 --lng 139.7583  # 新橋駅中心
python3 search.py --format tsv > shops.tsv   # スプレッドシート用
```

### enrich.py

```bash
python3 enrich.py --input output/shops.json                  # フル実行（飲み放題込みコース＋5-8名個室必須）
python3 enrich.py --input output/shops.json --max-shops 5    # 先頭5件だけ試走
python3 enrich.py --input output/shops.json --show-all       # フィルタ落ちも理由付きで表示
python3 enrich.py --input output/shops.json --no-drink-filter  # 通常コース価格でフィルタ
python3 enrich.py --input output/shops.json --any-room       # 5-8名個室の明記を必須にしない
python3 enrich.py --input output/shops.json --concurrency 8  # 並列数
```

## 抽出ロジック（enrich.py）

| 項目 | 判定方法 |
|---|---|
| 飲み放題込みコース価格 | テキスト中で「飲み放題」の前後500文字以内にある `¥X,XXX 円` を全て抽出。最安値を採用。 |
| 通常コース価格 | 「コース」の前後300文字以内の価格(2000円〜)。飲み放題なしで会食する場合の参考。 |
| 完全個室 | 「完全個室」の文字列があれば○、「半個室」のみなら×、それ以外は? |
| 5-8名個室 | 「5/6/7/8名個室」「6名様まで」「中個室」などのパターン正規表現。 |
| 会食適性 | 「会食/接待/商談/落ち着いた/静かな/上質/おもてなし/VIP/...」のヒット数をスコア化。 |
| 喫煙可否 | 参考情報。フィルタには使わない。 |

最終的に会食適性スコア降順 → 価格昇順でソート出力されます。

## 制限事項

| 条件 | API取得可否 | enrich.py | 確認方法 |
|---|---|---|---|
| 個室あり | ○ | - | API |
| 飲み放題あり | ○ | - | API |
| 飲み放題込みコースが8800円以下 | × | △ 正規表現で抽出 | コースページ目視確認推奨 |
| **完全個室**（半個室除外） | × | △ キーワード判定 | 店舗説明文を読む |
| **5-8名対応個室** | × | △ パターン判定 | 電話確認が確実 |
| 静か・落ち着いた雰囲気 | × | △ キーワードスコア | クチコミも参照 |

正規表現＋キーワード判定なので誤検出はあります。**会食前に電話で「日付・人数・コース・個室タイプ」を確定確認**してください。

## 範囲コード (--range)

| 値 | 半径 |
|---|---|
| 1 | 300m |
| 2 | 500m |
| 3 | 1km |
| 4 | 2km |
| 5 | 3km (default, タクシー10分相当) |

## API

[ホットペッパーグルメサーチAPI](https://webservice.recruit.co.jp/doc/hotpepper/reference.html)
