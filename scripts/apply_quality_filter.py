#!/usr/bin/env python3
"""Apply config/quality.json to articles already in the database.

New items are filtered during ingestion. This script reconciles the existing
rows: matching rows get ``filtered=1`` (hidden from every query) and a
``filter_reason``; rows that no longer match are restored.

Dry-run by default. Pass ``--apply`` to write.

    python scripts/apply_quality_filter.py
    python scripts/apply_quality_filter.py --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from db import connect, init_db  # noqa: E402
from quality import QualityFilter  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write filtered flags")
    parser.add_argument("--samples", type=int, default=3, help="samples per feed")
    parser.add_argument("--feed", default="", help="only inspect one feed id")
    args = parser.parse_args()

    conn = connect()
    init_db(conn)
    quality = QualityFilter()
    if not quality.enabled:
        print("quality filter is disabled in config/quality.json")
        return 0

    where = "WHERE feed_id=?" if args.feed else ""
    params = (args.feed,) if args.feed else ()
    rows = conn.execute(
        f"""SELECT id, title, summary, url, language, feed_id, feed_name,
                   COALESCE(filtered, 0) AS filtered, filter_reason
            FROM articles {where}
            ORDER BY published_at DESC""",
        params,
    ).fetchall()

    per_feed: Counter[str] = Counter()
    per_rule: Counter[str] = Counter()
    samples: dict[str, list[str]] = defaultdict(list)
    matches: dict[str, str] = {}
    for row in rows:
        reason = quality.match(
            row["title"] or "",
            row["summary"] or "",
            row["url"] or "",
            row["language"] or "",
            row["feed_id"] or "",
        )
        if not reason:
            continue
        matches[row["id"]] = reason
        per_feed[row["feed_name"] or row["feed_id"]] += 1
        per_rule[reason] += 1
        if len(samples[row["feed_name"] or row["feed_id"]]) < args.samples:
            samples[row["feed_name"] or row["feed_id"]].append(
                f"[{reason}] {row['title']}"
            )

    already = sum(1 for row in rows if row["filtered"])
    print(f"articles scanned : {len(rows):,}")
    print(f"currently hidden : {already:,}")
    print(f"matching rules   : {len(matches):,}")
    print()
    print("by feed:")
    for name, count in per_feed.most_common():
        print(f"  {count:5,}  {name}")
    print()
    print("by rule:")
    for rule, count in per_rule.most_common():
        print(f"  {count:5,}  {rule}")
    print()
    for name, _ in per_feed.most_common():
        print(f"## {name}")
        for line in samples[name]:
            print("  ", line)
        print()

    hidden_ids = {row["id"] for row in rows if row["filtered"]}
    newly_hidden = len(set(matches) - hidden_ids)
    restored = len(hidden_ids - set(matches))
    print(f"would hide newly : {newly_hidden:,}")
    print(f"would restore    : {restored:,}")

    if not args.apply:
        print("\ndry-run; pass --apply to write")
        conn.close()
        return 0

    conn.execute("BEGIN")
    for row in rows:
        reason = matches.get(row["id"])
        conn.execute(
            "UPDATE articles SET filtered=?, filter_reason=? WHERE id=?",
            (1 if reason else 0, reason, row["id"]),
        )
    conn.commit()
    print("\napplied")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
