#!/usr/bin/env python3
"""Backfill event location and cross-language signatures for stored articles.

Run after editing config/gazetteer.json or after upgrading from a version
without the event layer. No network access is required.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from db import connect, init_db  # noqa: E402
from eventgraph import graph  # noqa: E402
from taxonomy import country_from_url, region_of  # noqa: E402


def main() -> None:
    eg = graph()
    conn = connect()
    init_db(conn)
    rows = conn.execute(
        "SELECT id, title, summary, feed_id, publisher_url, country, region FROM articles"
    ).fetchall()
    started = time.time()
    countries: Counter = Counter()
    located = 0
    topics: Counter = Counter()
    fixed_country = 0
    for index, row in enumerate(rows, 1):
        event = eg.extract(row["title"], row["summary"] or "")
        country = row["country"]
        region = row["region"]
        if (row["feed_id"] or "").startswith("gnews-") and row["publisher_url"]:
            inferred = country_from_url(row["publisher_url"], country)
            if inferred and inferred != country:
                country = inferred
                region = region_of(inferred)
                fixed_country += 1
        conn.execute(
            """
            UPDATE articles SET country=?, region=?, event_country=?, event_region=?, event_places=?,
                event_entities=?, event_topics=?, event_confidence=? WHERE id=?
            """,
            (
                country, region, event["event_country"],
                event["event_region"],
                json.dumps(event["event_places"], ensure_ascii=False),
                json.dumps(event["event_entities"], ensure_ascii=False),
                json.dumps(event["event_topics"], ensure_ascii=False),
                event["event_confidence"],
                row["id"],
            ),
        )
        if event["event_region"]:
            located += 1
        if event["event_country"]:
            countries[event["event_country"]] += 1
        for topic in event["event_topics"]:
            topics[topic["id"]] += 1
        if index % 250 == 0:
            conn.commit()
    conn.commit()
    total = len(rows)
    print(
        f"enriched {total} articles in {time.time()-started:.1f}s; "
        f"located={located} ({located/max(total,1)*100:.1f}%); "
        f"fixed aggregator countries={fixed_country}"
    )
    print("top countries:", countries.most_common(12))
    print("top topics:", topics.most_common(12))
    conn.close()


if __name__ == "__main__":
    main()
