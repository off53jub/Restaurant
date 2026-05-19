# Restaurant Filter

虎ノ門エリア（2km圏）で「個室＋飲み放題＋予算8800円以下＋席で喫煙可」のレストランを探すCLIツール。

2段階処理：
1. **search.py** — ホットペッパーAPIで一次取得（個室・飲み放題・エリアでフィルタ）
2. **enrich.py** — 各店のページを取得して、飲み放題込みコース価格・完全個室・喫煙可否を正規表現＋キーワードで抽出

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env を編集して HOTPEPPER_API_KEY を実際のキーに置換
```

## 使い方（一気通貫）

```bash
mkdir -p output

# Step 1: ホットペッパーAPIで候補取得
python3 search.py --save-json output/shops.json --format tsv > output/shops.tsv

# Step 2: 各店のページをfetchしてコース・個室・喫煙を抽出
python3 enrich.py --input output/shops.json --output output/enriched.json
```

## 個別オプション

### search.py

```bash
python3 search.py                            # 虎ノ門2km/個室/飲み放題/8800円以下
python3 search.py --range 3                  # 半径1kmに変更
python3 search.py --lat 35.6663 --lng 139.7583  # 新橋駅中心
python3 search.py --format tsv > shops.tsv   # スプレッドシート用
```

### enrich.py

```bash
python3 enrich.py --input output/shops.json                # フル実行
python3 enrich.py --input output/shops.json --max-shops 5  # 先頭5件だけ試走
python3 enrich.py --input output/shops.json --show-all     # フィルタ落ちも表示
python3 enrich.py --input output/shops.json --concurrency 8 # 並列数
```

## 抽出ロジック（enrich.py）

| 項目 | 判定方法 |
|---|---|
| 飲み放題込みコース価格 | テキスト中で「飲み放題」の前後500文字以内にある `¥X,XXX 円` を全て抽出。最安値を採用。 |
| 完全個室 | 「完全個室」の文字列があれば○、「半個室」のみなら×、それ以外は? |
| 喫煙可否 | キーワード優先順位で判定: `喫煙可/シガー/加熱式専用` → 可、`全席禁煙/全面禁煙` → 不可、`分煙` → 一部可、なし → 不明 |

## 制限事項

| 条件 | API取得可否 | enrich.py | 確認方法 |
|---|---|---|---|
| 個室あり | ○ | - | API |
| 飲み放題あり | ○ | - | API |
| 飲み放題込みコースが8800円以下 | × | △ 正規表現で抽出 | コースページ目視確認推奨 |
| **完全個室**（半個室除外） | × | △ キーワード判定 | 店舗説明文を読む |
| **席で喫煙可** | × | △ キーワード判定 | **電話確認が確実** |

正規表現＋キーワード判定なので誤検出はあります。**最終的な「席で喫煙可」は法令上店舗確認が必須**です。出力されたURLと電話番号で各店確認してください。

## 範囲コード (--range)

| 値 | 半径 |
|---|---|
| 1 | 300m |
| 2 | 500m |
| 3 | 1km |
| 4 | 2km (default) |
| 5 | 3km |

## API

[ホットペッパーグルメサーチAPI](https://webservice.recruit.co.jp/doc/hotpepper/reference.html)
