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

## 東京23区データベース版（db.py / ingest.py / enrich_db.py / query.py）

毎回APIを叩く代わりに、**23区全域の店舗をSQLiteに貯めて何度でも高速検索**するモード。

```
ingest.py  → HotPepper APIで23区の店舗を取得し shops テーブルに UPSERT
enrich_db.py → 未enrich/期限切れの店だけページ取得して judgements に UPSERT
query.py   → プリセット or アドホック条件 + FTS全文検索で抽出
```

### 初回構築

DB は GitHub Release アセット (`db-snapshot/shops.db.gz`) に永続化されます。

**A. 既存のRelease DBから始める（推奨・最速）**

```bash
make install
make pull-db          # Release からDB(gz)を取得し展開（数秒〜十数秒）
python3 query.py --preset kaishoku
```

**B. ゼロから自前構築する**

```bash
make install
make ingest           # 23区44中心からAPI取得（数分、約28,000店）
make enrich           # 全店のページ取得・判定（数時間、80店/分）
make push-db          # 完成したDBをRelease (db-snapshot) にアップロード（初回のみシード）
```

`enrich_db.py` は50件ごとにDBコミットし、対象を「judgements未作成 or `--max-age-days`日より古い」で選ぶため、**中断しても `make enrich` 再実行でレジューム**できます。

### 検索

```bash
make list                                    # プリセット一覧
python3 query.py --preset kaishoku           # 役員会食（虎ノ門圏）
python3 query.py --preset date_shinjuku --limit 10
python3 query.py --preset instagram_shinjuku

# アドホック（プリセット非依存）
python3 query.py --area 銀座 --area 新橋 --price-min 5000 --price-max 8000 \
                 --fully-private --calm-min 60 --limit 20

# FTS全文検索（名前・住所・アクセス・キャッチ）
python3 query.py --fts "個室 AND 銀座" --price-min 6000 --price-max 10000
```

プリセットは `filter.py` の `PRESETS` 辞書に1エントリ追加するだけで増やせます。

### 月次メンテナンス

店舗の開店/閉店/コース改定はHotPepper側で随時起きるため、月1回の再取得を推奨。

```bash
make refresh   # ingest（全店再fetch・last_seen_at更新） → enrich（30日超のみ再判定）
make push-db   # 更新後のDBをReleaseへ上書き
```

閉店検知は `shops.last_seen_at` が最新ingestより古い店を抽出すれば可能：

```sql
SELECT name, address, last_seen_at FROM shops
WHERE last_seen_at < (SELECT MAX(last_seen_at) FROM shops);
```

#### DB の永続化（GitHub Release）

| 場所 | 内容 |
|---|---|
| Release タグ `db-snapshot` | 常に最新のDBスナップショット。月次で上書き |
| アセット `shops.db.gz` | gzip圧縮されたSQLite DB（実測 134MB→22MB、約15%） |

`make pull-db` / `make push-db` で双方向に同期。CIから書き込むため `gh` CLI が依存（ローカルでは要 `gh auth login`、CI上ではGITHUB_TOKENが自動）。

#### 自動実行

**A. クラウド月次（推奨・無人運用可）** — `.github/workflows/monthly-refresh.yml` が毎月1日4時(JST)に実行:
1. Release から前回DBを復元
2. ingest + 差分enrich
3. VACUUM + gzip して Release を上書き

リポジトリ secrets に `HOTPEPPER_API_KEY` を登録するだけで動作。手動キック (`workflow_dispatch`) も可。

**B. ローカル cron / launchd / systemd**

cron (Linux), 毎月1日 4時:
```cron
0 4 1 * * cd /path/to/Restaurant && make refresh && make push-db >> refresh.log 2>&1
```

launchd (macOS) — `~/Library/LaunchAgents/com.restaurant.refresh.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.restaurant.refresh</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string><string>-c</string>
    <string>cd /path/to/Restaurant && make refresh && make push-db >> refresh.log 2>&1</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Day</key><integer>1</integer><key>Hour</key><integer>4</integer><key>Minute</key><integer>0</integer></dict>
</dict></plist>
```
`launchctl load ~/Library/LaunchAgents/com.restaurant.refresh.plist` で登録。

systemd timer (Linux): `restaurant-refresh.service` + `restaurant-refresh.timer` (`OnCalendar=*-*-01 04:00:00`)。

### スキーマ

| テーブル | 役割 |
|---|---|
| `shops` | 店マスタ。API生JSON(`raw_json`)、`first_seen_at`/`last_seen_at`/`fetched_at` |
| `judgements` | enrich結果。価格・個室・会食/インスタスコア・雰囲気・`enriched_at` |
| `shops_fts` | FTS5全文検索（name/kana/address/access/catch、トリガで自動同期） |
| `ingest_runs` | ingest履歴（新規/更新件数） |

DBファイル（`db/`, `*.db`）は `.gitignore` 済み。サイズが大きくバージョン管理に不向きなため、リポジトリはコード管理に専念し、DB本体はローカル/外部ストレージに置く方針。

## API

[ホットペッパーグルメサーチAPI](https://webservice.recruit.co.jp/doc/hotpepper/reference.html)
