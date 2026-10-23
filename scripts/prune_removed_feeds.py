#!/usr/bin/env python3
"""Remove articles and feed state for sources no longer in config/feeds.json.

This is intentionally explicit: switching to a curated source catalog can
leave historical articles from removed general-news feeds in the timeline.
Run with --dry-run first, then stop the server and run with --backup.

Example:
    python scripts/prune_removed_feeds.py --dry-run
    python scripts/prune_removed_feeds.py --backup data/news-before-specialized.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from db import DB_PATH, connect, init_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--backup", help="write a SQLite backup before deleting")
    args = parser.parse_args()

    config = json.loads((ROOT / "config" / "feeds.json").read_text(encoding="utf-8"))
    keep = [feed["id"] for feed in config.get("feeds", [])]
    if not keep:
        print("Refusing to prune: config contains no feeds.")
        return 2

    if args.backup:
        target = Path(args.backup)
        if not target.is_absolute():
            target = ROOT / target
        target.parent.mkdir(parents=True, exist_ok=True)
        source = connect()
        backup = sqlite3.connect(str(target))
        with backup:
            source.backup(backup)
        backup.close()
        source.close()
        print(f"backup: {target}")

    conn = connect()
    init_db(conn)
    placeholders = ",".join("?" for _ in keep)
    article_count = conn.execute(
        f"SELECT COUNT(*) FROM articles WHERE feed_id NOT IN ({placeholders})", keep
    ).fetchone()[0]
    feed_count = conn.execute(
        f"SELECT COUNT(*) FROM feeds WHERE id NOT IN ({placeholders})", keep
    ).fetchone()[0]
    total_articles = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]

    print(f"keep feeds: {len(keep)}")
    print(f"articles to remove: {article_count} / {total_articles}")
    print(f"feed state rows to remove: {feed_count}")
    if args.dry_run:
        conn.close()
        return 0

    conn.execute(f"DELETE FROM articles WHERE feed_id NOT IN ({placeholders})", keep)
    conn.execute(f"DELETE FROM feeds WHERE id NOT IN ({placeholders})", keep)
    conn.commit()
    conn.execute("VACUUM")
    conn.commit()
    remaining = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    print(f"remaining articles: {remaining}")
    print(f"database: {DB_PATH}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
