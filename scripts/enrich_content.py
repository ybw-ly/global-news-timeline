#!/usr/bin/env python3
"""Backfill hard-news / analysis / opinion labels for stored articles."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from contenttype import ContentTypeClassifier  # noqa: E402
from db import connect, init_db  # noqa: E402


def main() -> None:
    classifier = ContentTypeClassifier()
    feed_data = json.loads((ROOT / "config" / "feeds.json").read_text(encoding="utf-8"))
    hints = {
        feed["id"]: feed.get("content_hint")
        for feed in feed_data.get("feeds", [])
    }
    conn = connect()
    init_db(conn)
    rows = conn.execute(
        "SELECT id, title, summary, url, language, rss_categories, feed_id FROM articles"
    ).fetchall()
    counts: Counter = Counter()
    for row in rows:
        try:
            categories = json.loads(row["rss_categories"] or "[]")
        except Exception:
            categories = []
        result = classifier.classify(
            row["title"], row["summary"] or "", row["url"] or "",
            categories if isinstance(categories, list) else [], row["language"] or "en",
            hints.get(row["feed_id"]),
        )
        counts[result["content_type"]] += 1
        conn.execute(
            "UPDATE articles SET content_type=?, content_type_terms=? WHERE id=?",
            (
                result["content_type"],
                json.dumps(result["content_type_terms"], ensure_ascii=False),
                row["id"],
            ),
        )
    conn.commit()
    print(f"classified {len(rows)} articles: {dict(counts)}")
    conn.close()


if __name__ == "__main__":
    main()
