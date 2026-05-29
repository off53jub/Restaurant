#!/usr/bin/env python3
"""自分の訪問記録CLI。HotPepperの28k店DBと紐付けつつ、DB外の店も手入力可能。

使い方:
  # 名前検索→候補から番号で選んで追加
  python visit.py add --search "花びし" --rating 4 --cost 8000 \
      --scene kaishoku --date 2025-12-01 --notes "個室静か、コース実食"

  # shop_id 直指定
  python visit.py add --shop-id J003559227 --rating 5 --date 2025-12-01

  # DB外の店（都外/ミシュラン等）
  python visit.py add --manual --name "未在" --address "京都市東山区" \
      --rating 5 --cost 30000 --date 2026-01-15

  # 一覧
  python visit.py list                          # 全件
  python visit.py list --rating-min 4           # ★4+
  python visit.py list --scene date --year 2026
  python visit.py list --format csv > visits.csv

  # 編集・削除
  python visit.py edit --id 7 --rating 5 --notes "..."
  python visit.py rm --id 7
"""
import argparse
import csv
import datetime as dt
import json
import sys

import db as dbmod


SCENES = ["kaishoku", "date", "family", "friends", "solo", "business", "other"]


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def normalize_date(s):
    """'today' / 'YYYY-MM-DD' / 'YYYYMMDD' を受け付け 'YYYY-MM-DD' に正規化。"""
    if not s or s == "today":
        return dt.date.today().isoformat()
    try:
        return dt.date.fromisoformat(s).isoformat()
    except ValueError:
        pass
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    raise SystemExit(f"日付フォーマット不正: {s}（YYYY-MM-DD で指定）")


def fts_search(conn, query, limit=10):
    """FTS5 で店名/住所を検索し候補を返す。"""
    sql = """
    SELECT s.id, s.name, s.address, s.genre_name
    FROM shops s JOIN shops_fts f ON f.rowid = s.rowid
    WHERE shops_fts MATCH ?
    LIMIT ?
    """
    return list(conn.execute(sql, (query, limit)))


def pick_shop_id(conn, args):
    """add時のshop_id決定: --manual / --shop-id / --search のどれか。"""
    if args.manual:
        if not args.name:
            raise SystemExit("--manual には --name が必須")
        return None
    if args.shop_id:
        row = conn.execute("SELECT id, name FROM shops WHERE id = ?", (args.shop_id,)).fetchone()
        if not row:
            raise SystemExit(f"shop_id {args.shop_id} がDBに存在しません")
        return args.shop_id
    if args.search:
        cands = fts_search(conn, args.search, 10)
        if not cands:
            raise SystemExit(f"検索 '{args.search}' に該当なし。--manual も検討")
        if len(cands) == 1:
            print(f"自動選択: {cands[0]['name']} ({cands[0]['address']})", file=sys.stderr)
            return cands[0]["id"]
        print("候補:", file=sys.stderr)
        for i, r in enumerate(cands, 1):
            print(f"  {i}. {r['name']} / {r['genre_name']} / {r['address']}", file=sys.stderr)
        choice = input("番号 (0=中止): ").strip()
        if not choice or choice == "0":
            raise SystemExit("中止")
        idx = int(choice) - 1
        return cands[idx]["id"]
    raise SystemExit("--shop-id, --search, --manual のいずれかが必要")


def cmd_add(conn, args):
    shop_id = pick_shop_id(conn, args)
    visited_at = normalize_date(args.date)
    now = now_iso()
    if args.scene and args.scene not in SCENES:
        print(f"WARN: 未知のシーン '{args.scene}'（既知: {','.join(SCENES)})", file=sys.stderr)
    cols = {
        "shop_id": shop_id,
        "manual_name": args.name if args.manual else None,
        "manual_address": args.address if args.manual else None,
        "manual_url": args.url if args.manual else None,
        "visited_at": visited_at,
        "rating": args.rating,
        "cost_per_person": args.cost,
        "scene": args.scene,
        "companions": args.companions,
        "course_name": args.course,
        "private_room": int(args.private_room) if args.private_room is not None else None,
        "would_revisit": int(args.would_revisit) if args.would_revisit is not None else None,
        "notes": args.notes,
        "tags": args.tags,
        "created_at": now,
        "updated_at": now,
    }
    keys = ", ".join(cols.keys())
    placeholders = ", ".join(f":{k}" for k in cols)
    cur = conn.execute(f"INSERT INTO visits ({keys}) VALUES ({placeholders})", cols)
    conn.commit()
    print(f"追加 id={cur.lastrowid} / {visited_at} / shop_id={shop_id or '(manual)'}")


def cmd_edit(conn, args):
    row = conn.execute("SELECT * FROM visits WHERE id = ?", (args.id,)).fetchone()
    if not row:
        raise SystemExit(f"id {args.id} が見つかりません")
    updates = {}
    for field, val in [
        ("rating", args.rating), ("cost_per_person", args.cost),
        ("scene", args.scene), ("companions", args.companions),
        ("course_name", args.course), ("notes", args.notes), ("tags", args.tags),
    ]:
        if val is not None:
            updates[field] = val
    if args.date:
        updates["visited_at"] = normalize_date(args.date)
    if args.private_room is not None:
        updates["private_room"] = int(args.private_room)
    if args.would_revisit is not None:
        updates["would_revisit"] = int(args.would_revisit)
    if not updates:
        raise SystemExit("変更項目がありません")
    updates["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = args.id
    conn.execute(f"UPDATE visits SET {sets} WHERE id = :id", updates)
    conn.commit()
    print(f"更新 id={args.id} / 変更{len(updates)-2}項目")


def cmd_rm(conn, args):
    n = conn.execute("DELETE FROM visits WHERE id = ?", (args.id,)).rowcount
    conn.commit()
    print(f"削除: {n}件")


def visit_to_dict(v):
    d = dict(v)
    name = d.get("name") or d.get("manual_name") or "(unknown)"
    addr = d.get("address") or d.get("manual_address") or ""
    url = d.get("pc_url") or d.get("manual_url") or ""
    return {
        "id": d["id"],
        "visited_at": d["visited_at"],
        "name": name,
        "address": addr,
        "rating": d["rating"],
        "cost": d["cost_per_person"],
        "scene": d["scene"],
        "companions": d["companions"],
        "course": d["course_name"],
        "private_room": d["private_room"],
        "would_revisit": d["would_revisit"],
        "notes": d["notes"],
        "tags": d["tags"],
        "url": url,
        "in_db": d.get("shop_id") is not None,
    }


def cmd_list(conn, args):
    where, params = [], []
    if args.rating_min is not None:
        where.append("rating >= ?"); params.append(args.rating_min)
    if args.scene:
        where.append("scene = ?"); params.append(args.scene)
    if args.year:
        where.append("visited_at LIKE ?"); params.append(f"{args.year}%")
    if args.area:
        where.append("(COALESCE(s.address, v.manual_address) LIKE ?)")
        params.append(f"%{args.area}%")
    if args.would_revisit:
        where.append("would_revisit = 1")
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    sql = f"""
    SELECT v.*, s.name, s.address, s.pc_url, s.genre_name
    FROM visits v
    LEFT JOIN shops s ON s.id = v.shop_id
    {where_sql}
    ORDER BY v.visited_at DESC, v.id DESC
    """
    rows = list(conn.execute(sql, params))
    dicts = [visit_to_dict(r) for r in rows]
    if args.limit > 0:
        dicts = dicts[: args.limit]

    if args.format == "json":
        print(json.dumps(dicts, ensure_ascii=False, indent=2))
        return
    if args.format in ("csv", "tsv"):
        if not dicts:
            return
        delim = "\t" if args.format == "tsv" else ","
        w = csv.DictWriter(sys.stdout, fieldnames=list(dicts[0].keys()), delimiter=delim)
        w.writeheader()
        w.writerows(dicts)
        return
    # text
    print(f"訪問記録: {len(dicts)}件\n" + "=" * 70)
    for d in dicts:
        star = ("★" * (d["rating"] or 0)).ljust(5, "☆") if d["rating"] else "—"
        cost = f"{d['cost']:,}円" if d["cost"] else "—"
        scene = f"[{d['scene']}]" if d["scene"] else ""
        revisit = " ♥再訪" if d["would_revisit"] else ""
        marker = "" if d["in_db"] else " (手入力)"
        print(f"\n#{d['id']} {d['visited_at']} {star} {scene}{revisit}{marker}")
        print(f"   {d['name']} / {d['address']}")
        if d["course"]:
            print(f"   コース: {d['course']} / 一人 {cost}")
        elif d["cost"]:
            print(f"   一人 {cost}")
        if d["companions"]:
            print(f"   同席: {d['companions']}")
        if d["notes"]:
            print(f"   メモ: {d['notes']}")
        if d["tags"]:
            print(f"   タグ: {d['tags']}")
        if d["url"]:
            print(f"   URL: {d['url']}")


def main():
    ap = argparse.ArgumentParser(description="訪問記録CLI")
    ap.add_argument("--db", default="db/shops.db")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="記録を追加")
    grp = a.add_mutually_exclusive_group()
    grp.add_argument("--shop-id")
    grp.add_argument("--search", help="FTS検索（複数候補時は番号選択）")
    a.add_argument("--manual", action="store_true", help="DB外の店として手入力")
    a.add_argument("--name", help="--manual 時の店名")
    a.add_argument("--address", help="--manual 時の住所")
    a.add_argument("--url", help="--manual 時のURL")
    a.add_argument("--date", default="today", help="YYYY-MM-DD or 'today'")
    a.add_argument("--rating", type=int, choices=range(1, 6))
    a.add_argument("--cost", type=int, help="一人あたり円")
    a.add_argument("--scene", help=f"({'/'.join(SCENES)})")
    a.add_argument("--companions")
    a.add_argument("--course", help="コース名/価格")
    a.add_argument("--private-room", type=int, choices=[0, 1])
    a.add_argument("--would-revisit", type=int, choices=[0, 1])
    a.add_argument("--notes")
    a.add_argument("--tags", help="カンマ区切り")

    e = sub.add_parser("edit", help="記録を更新")
    e.add_argument("--id", type=int, required=True)
    e.add_argument("--date"); e.add_argument("--rating", type=int, choices=range(1, 6))
    e.add_argument("--cost", type=int); e.add_argument("--scene")
    e.add_argument("--companions"); e.add_argument("--course")
    e.add_argument("--private-room", type=int, choices=[0, 1])
    e.add_argument("--would-revisit", type=int, choices=[0, 1])
    e.add_argument("--notes"); e.add_argument("--tags")

    r = sub.add_parser("rm", help="記録を削除")
    r.add_argument("--id", type=int, required=True)

    l = sub.add_parser("list", help="一覧")
    l.add_argument("--rating-min", type=int)
    l.add_argument("--scene")
    l.add_argument("--year", type=int)
    l.add_argument("--area", help="住所に含む語")
    l.add_argument("--would-revisit", action="store_true", help="再訪意思のみ")
    l.add_argument("--limit", type=int, default=0)
    l.add_argument("--format", choices=["text", "csv", "tsv", "json"], default="text")

    args = ap.parse_args()
    conn = dbmod.init_db(args.db)  # スキーマ未作成でも自動作成
    {"add": cmd_add, "edit": cmd_edit, "rm": cmd_rm, "list": cmd_list}[args.cmd](conn, args)


if __name__ == "__main__":
    main()
