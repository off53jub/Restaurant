.PHONY: install test ingest ingest-gnavi ingest-osm enrich enrich-retry refresh query list q closures report visits stats compare recommend google-enrich social-enrich reviews wiki-enrich hp-reviews geo-enrich youtube-enrich foods osm-gap pairs companions pull-db push-db push-db-seed

PY := .venv/bin/python
DB := db/shops.db
DB_GZ := $(DB).gz
DB_RELEASE_TAG ?= db-snapshot

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt
	.venv/bin/pip install -r requirements-dev.txt

# 抽出ロジックの退行防止テスト
test:
	$(PY) -m pytest -q

# 23区の店舗を HotPepper API から取得（数分）
ingest:
	$(PY) ingest.py --db $(DB)

# 23区の店舗を ぐるなび API から取得（HotPepperと相互補完）
ingest-gnavi:
	$(PY) ingest_gnavi.py --db $(DB)

# 23区の店舗を OpenStreetMap (Overpass) から取得（無料・キー不要）
ingest-osm:
	$(PY) ingest_osm.py --db $(DB)

# DBの未 enrich 店 + 30日超 enrich 店を処理（数時間）
enrich:
	$(PY) enrich_db.py --db $(DB) --concurrency 12 --delay 0.3

# fetch_error が残っている店だけ再取得（リトライ込み）
enrich-retry:
	$(PY) enrich_db.py --db $(DB) --retry-errors --concurrency 8 --delay 0.5

# 閉店/移転候補（直近の full ingest 後に意味を持つ）
closures:
	$(PY) query.py --db $(DB) --closures

# 写真・地図付きHTMLレポート 例: make report PRESET=kaishoku OUT=out.html
report:
	$(PY) report.py --db $(DB) --preset $(PRESET) --out $(OUT)

# 訪問記録の一覧
visits:
	$(PY) visit.py --db $(DB) list $(ARGS)

# 同席者プロファイル 例: make companions ARGS="--name 上司A"
companions:
	$(PY) visit.py --db $(DB) companions $(ARGS)

# 1次会×2次会の鉄板コンビ 例: make pairs PRESET=kaishoku OUT=output/p.html
pairs:
	$(PY) pairs.py --db $(DB) --preset $(PRESET) --out $(OUT)

# 訪問ダッシュボード（集計）
stats:
	$(PY) visit.py --db $(DB) stats

# 比較HTML  例: make compare IDS="J003559227 J001238039" OUT=cmp.html
compare:
	$(PY) compare.py --db $(DB) --ids $(IDS) --out $(OUT)

# 訪問履歴ベースのリコメンド
recommend:
	$(PY) recommend.py --db $(DB) $(ARGS)

# Google評価取得（要GOOGLE_PLACES_API_KEY） 例: make google-enrich ARGS="--visited-only"
google-enrich:
	$(PY) google_enrich.py --db $(DB) $(ARGS)

# 公式サイトからSNS+OGメタ取得 例: make social-enrich ARGS="--osm-with-website --limit 100"
social-enrich:
	$(PY) enrich_social.py --db $(DB) $(ARGS)

# 店の口コミ要約表示 例: make reviews ARGS="--shop-id J003559227"
reviews:
	$(PY) reviews.py --db $(DB) $(ARGS)

# Wikidata/Wikipedia 連携 例: make wiki-enrich ARGS="--visited-only"
wiki-enrich:
	$(PY) enrich_wiki.py --db $(DB) $(ARGS)

# HotPepperページの口コミ・件数・シーン別を取得（無料・現行スクレイプと同根拠）
hp-reviews:
	$(PY) enrich_reviews_hotpepper.py --db $(DB) $(ARGS)

# 緯度経度→区名 逆ジオコーディング（OSM店の区不明を埋める） 例: ARGS="--source osm"
geo-enrich:
	$(PY) enrich_geo.py --db $(DB) $(ARGS)

# YouTube話題度（要YOUTUBE_API_KEY） 例: ARGS="--visited-only"
youtube-enrich:
	$(PY) enrich_youtube.py --db $(DB) $(ARGS)

# FOODSオープンデータCSV取込 例: make foods CSV=~/Downloads/tokyo.csv
foods:
	$(PY) ingest_foods.py --db $(DB) --csv $(CSV)

# OSM固有(HotPepper未掲載)店のHTML発掘 例: make osm-gap AREA=港区 OUT=out/gap.html
osm-gap:
	$(PY) osm_gap.py --db $(DB) --area $(AREA) --out $(OUT)

# 月次差分: 全店再 fetch + 30日超のみ enrich
refresh: ingest enrich

# プリセット一覧
list:
	$(PY) query.py --list-presets

# 例: make q PRESET=kaishoku
q:
	$(PY) query.py --db $(DB) --preset $(PRESET) $(ARGS)

# ---- DB <-> GitHub Release (永続化) ----
# 前提: gh CLI がインストール済み・認証済み（ローカル）
# CI上ではGITHUB_TOKENが自動的にghに渡る

# Release から DB を取得して db/ に展開
pull-db:
	@mkdir -p db
	gh release download $(DB_RELEASE_TAG) --pattern shops.db.gz --dir db --clobber
	gunzip -f $(DB_GZ)
	@echo "Pulled $(DB) ($$(du -h $(DB) | cut -f1))"

# 既存 Release アセットを今のDBで上書き（タグが無ければ作成）
push-db:
	@test -f $(DB) || (echo "ERROR: $(DB) が無い"; exit 1)
	$(PY) -c "import sqlite3; c=sqlite3.connect('$(DB)'); c.execute('VACUUM'); c.close()"
	gzip -9 -kf $(DB)
	@if gh release view $(DB_RELEASE_TAG) >/dev/null 2>&1; then \
	  gh release upload $(DB_RELEASE_TAG) $(DB_GZ) --clobber; \
	else \
	  gh release create $(DB_RELEASE_TAG) $(DB_GZ) \
	    --title "DB snapshot" \
	    --notes "23区レストランDB（gzip圧縮）。月次自動更新。"; \
	fi
	@rm -f $(DB_GZ)
	@echo "Pushed $(DB) to release tag $(DB_RELEASE_TAG)"

# 初回シード（ローカルで作ったDBを最初にRelease化するとき）
push-db-seed: push-db
