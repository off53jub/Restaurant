# Restaurant Filter

虎ノ門エリア（2km圏）で「個室＋飲み放題＋予算8800円以下＋席で喫煙可」のレストランを探すCLIツール。

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env を編集して HOTPEPPER_API_KEY を実際のキーに置換
```

## 使い方

```bash
# デフォルト: 虎ノ門駅中心 2km / 個室 / 飲み放題 / 8800円以下
python3 search.py

# 半径を変える
python3 search.py --range 3   # 1km

# 別エリアで使う（例: 新橋駅）
python3 search.py --lat 35.6663 --lng 139.7583

# 生レスポンスを保存（後段の解析用）
python3 search.py --save-json output/raw.json

# TSV出力（スプレッドシート貼り付け用）
python3 search.py --format tsv > shops.tsv
```

## 制限事項

ホットペッパーAPIだけでは以下は確定できないので、出力されたURLで各店を個別確認する必要がある：

| 条件 | API取得可否 | 確認方法 |
|---|---|---|
| 個室あり | ○ (フィルタ可) | API |
| 飲み放題あり | ○ (フィルタ可) | API |
| 予算8800円以下 | △ (平均ディナー予算ベース) | コースページで実額確認 |
| **完全個室**（半個室除外） | × | 店舗ページ説明文を読む |
| **席で喫煙可** | × (改正健康増進法以降フィルタなし) | 電話確認が確実 |
| 飲み放題込みコースが8800円以下 | × | コースページで確認 |

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
