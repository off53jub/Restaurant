.PHONY: install ingest enrich refresh query

PY := .venv/bin/python
DB := db/shops.db

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

# 23区の店舗を HotPepper API から取得（数分）
ingest:
	$(PY) ingest.py --db $(DB)

# DBの未 enrich 店 + 30日超 enrich 店を処理（数時間）
enrich:
	$(PY) enrich_db.py --db $(DB) --concurrency 12 --delay 0.3

# 月次差分: 全店再 fetch + 30日超のみ enrich
refresh: ingest enrich

# プリセット一覧
list:
	$(PY) query.py --list-presets

# 例: make q PRESET=kaishoku
q:
	$(PY) query.py --db $(DB) --preset $(PRESET) $(ARGS)
