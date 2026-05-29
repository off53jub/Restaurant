"""SQLite DB schema for the Tokyo 23-ward restaurant DB."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS shops (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_kana TEXT,
    address TEXT,
    station_name TEXT,
    lat REAL,
    lng REAL,
    genre_name TEXT,
    budget_name TEXT,
    access TEXT,
    pc_url TEXT,
    private_room TEXT,
    free_drink TEXT,
    non_smoking TEXT,
    course TEXT,
    catch TEXT,
    capacity TEXT,
    party_capacity TEXT,
    raw_json TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS shops_address ON shops(address);
CREATE INDEX IF NOT EXISTS shops_genre ON shops(genre_name);
CREATE INDEX IF NOT EXISTS shops_last_seen ON shops(last_seen_at);

CREATE TABLE IF NOT EXISTS judgements (
    shop_id TEXT PRIMARY KEY REFERENCES shops(id) ON DELETE CASCADE,
    drink_course_min_yen INTEGER,
    drink_course_prices_json TEXT,
    course_min_yen_any INTEGER,
    course_prices_any_json TEXT,
    fully_private_room INTEGER,
    smoking_at_seat TEXT,
    smoking_evidence TEXT,
    private_evidence TEXT,
    kaishoku_score INTEGER NOT NULL DEFAULT 0,
    kaishoku_hits_json TEXT,
    mid_room_ok INTEGER,
    mid_room_evidence TEXT,
    atmosphere_calm INTEGER,
    atmosphere_special INTEGER,
    instagram_score INTEGER NOT NULL DEFAULT 0,
    instagram_hits_json TEXT,
    fetch_error TEXT,
    enriched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS j_price ON judgements(drink_course_min_yen);
CREATE INDEX IF NOT EXISTS j_calm ON judgements(atmosphere_calm);
CREATE INDEX IF NOT EXISTS j_ig ON judgements(instagram_score);
CREATE INDEX IF NOT EXISTS j_enriched ON judgements(enriched_at);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    new_shops INTEGER NOT NULL DEFAULT 0,
    updated_shops INTEGER NOT NULL DEFAULT 0,
    centers INTEGER NOT NULL DEFAULT 0
);

-- 自分の訪問記録。shop_id がNULLならDB外の店(都外/ミシュラン等)を手入力で扱う。
CREATE TABLE IF NOT EXISTS visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id TEXT REFERENCES shops(id) ON DELETE SET NULL,
    manual_name TEXT,
    manual_address TEXT,
    manual_url TEXT,
    visited_at TEXT NOT NULL,            -- 'YYYY-MM-DD'
    rating INTEGER,                      -- 1-5
    cost_per_person INTEGER,             -- 円
    scene TEXT,                          -- kaishoku/date/family/business 等
    companions TEXT,                     -- フリーテキスト（同席者・人数）
    course_name TEXT,                    -- 例: 'おまかせコース 8800円'
    private_room INTEGER,                -- 0/1: 個室だったか
    would_revisit INTEGER,               -- 0/1: また来たい
    notes TEXT,
    tags TEXT,                           -- 'カウンター,日本酒充実' カンマ区切り
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (shop_id IS NOT NULL OR manual_name IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS visits_shop_id ON visits(shop_id);
CREATE INDEX IF NOT EXISTS visits_visited_at ON visits(visited_at);
CREATE INDEX IF NOT EXISTS visits_rating ON visits(rating);

CREATE VIRTUAL TABLE IF NOT EXISTS shops_fts USING fts5(
    name, name_kana, address, access, catch,
    content='shops', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS shops_ai AFTER INSERT ON shops BEGIN
  INSERT INTO shops_fts(rowid, name, name_kana, address, access, catch)
  VALUES (new.rowid, new.name, new.name_kana, new.address, new.access, new.catch);
END;
CREATE TRIGGER IF NOT EXISTS shops_ad AFTER DELETE ON shops BEGIN
  INSERT INTO shops_fts(shops_fts, rowid, name, name_kana, address, access, catch)
  VALUES('delete', old.rowid, old.name, old.name_kana, old.address, old.access, old.catch);
END;
CREATE TRIGGER IF NOT EXISTS shops_au AFTER UPDATE ON shops BEGIN
  INSERT INTO shops_fts(shops_fts, rowid, name, name_kana, address, access, catch)
  VALUES('delete', old.rowid, old.name, old.name_kana, old.address, old.access, old.catch);
  INSERT INTO shops_fts(rowid, name, name_kana, address, access, catch)
  VALUES (new.rowid, new.name, new.name_kana, new.address, new.access, new.catch);
END;
"""


def connect(path):
    conn = sqlite3.connect(path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path):
    conn = connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
