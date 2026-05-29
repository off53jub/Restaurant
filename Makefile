.PHONY: install test ingest enrich enrich-retry refresh query list q closures pull-db push-db push-db-seed

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

# DBの未 enrich 店 + 30日超 enrich 店を処理（数時間）
enrich:
	$(PY) enrich_db.py --db $(DB) --concurrency 12 --delay 0.3

# fetch_error が残っている店だけ再取得（リトライ込み）
enrich-retry:
	$(PY) enrich_db.py --db $(DB) --retry-errors --concurrency 8 --delay 0.5

# 閉店/移転候補（直近の full ingest 後に意味を持つ）
closures:
	$(PY) query.py --db $(DB) --closures

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
