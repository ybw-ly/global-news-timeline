#!/usr/bin/env python3
"""Re-run the deterministic classifier over stored articles.

Useful after editing config/lexicon.json. No RSS fetching is performed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from classifier import Classifier  # noqa: E402
from db import connect  # noqa: E402


def main() -> None:
    config = json.loads((ROOT / "config" / "feeds.json").read_text(encoding="utf-8"))
    hints = {feed["id"]: feed.get("category_hint") for feed in config["feeds"]}
    classifier = Classifier()
    conn = connect()
    rows = conn.execute(
        "SELECT id, title, summary, language, feed_id, category, category_terms FROM articles"
    ).fetchall()
    changed = 0
    counts: dict[str, int] = {}
    for row in rows:
        result = classifier.classify(
            row["title"], row["summary"] or "", row["language"], hints.get(row["feed_id"])
        )
        counts[result["category"]] = counts.get(result["category"], 0) + 1
        terms = json.dumps(result["terms"], ensure_ascii=False)
        if result["category"] != row["category"] or terms != row["category_terms"]:
            conn.execute(
                "UPDATE articles SET category=?, category_terms=?, category_scores=? WHERE id=?",
                (
                    result["category"],
                    terms,
                    json.dumps(result["scores"], ensure_ascii=False),
                    row["id"],
                ),
            )
            changed += 1
    conn.commit()
    print(f"reclassified {len(rows)} articles, {changed} changed")
    print("counts:", counts)
    conn.close()


if __name__ == "__main__":
    main()
