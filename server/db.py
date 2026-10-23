"""SQLite storage and query layer (standard library only)."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("NEWS_DB", ROOT / "data" / "news.db"))


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: Path | None = None) -> sqlite3.Connection:
    db = sqlite3.connect(str(path or DB_PATH), timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA busy_timeout=30000")
    return db


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            summary TEXT DEFAULT '',
            url TEXT NOT NULL,
            image_url TEXT,
            feed_id TEXT NOT NULL,
            feed_name TEXT,
            publisher TEXT NOT NULL,
            publisher_url TEXT,
            country TEXT,
            region TEXT,
            language TEXT,
            category TEXT NOT NULL DEFAULT 'other',
            category_terms TEXT,
            category_scores TEXT,
            ownership TEXT,
            published_at TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            is_demo INTEGER DEFAULT 0,
            event_country TEXT,
            event_region TEXT,
            event_places TEXT,
            event_entities TEXT,
            event_topics TEXT,
            event_confidence TEXT,
            content_type TEXT DEFAULT 'hard',
            content_type_terms TEXT,
            rss_categories TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_articles_publisher_fp
            ON articles(publisher, fingerprint);
        CREATE INDEX IF NOT EXISTS ix_articles_published ON articles(published_at DESC);
        CREATE INDEX IF NOT EXISTS ix_articles_category ON articles(category);
        CREATE INDEX IF NOT EXISTS ix_articles_region ON articles(region);
        CREATE INDEX IF NOT EXISTS ix_articles_language ON articles(language);
        CREATE INDEX IF NOT EXISTS ix_articles_country ON articles(country);
        CREATE INDEX IF NOT EXISTS ix_articles_publisher ON articles(publisher);

        CREATE TABLE IF NOT EXISTS feeds (
            id TEXT PRIMARY KEY,
            name TEXT,
            publisher TEXT,
            url TEXT,
            homepage TEXT,
            country TEXT,
            language TEXT,
            ownership TEXT,
            kind TEXT,
            category_hint TEXT,
            refresh_minutes INTEGER DEFAULT 30,
            max_items INTEGER DEFAULT 40,
            enabled INTEGER DEFAULT 1,
            etag TEXT,
            last_modified TEXT,
            last_fetch_at TEXT,
            last_status TEXT,
            last_error TEXT,
            last_count INTEGER DEFAULT 0,
            total_fetched INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS translations (
            text_hash TEXT NOT NULL,
            target TEXT NOT NULL,
            source_text TEXT,
            translated_text TEXT,
            model TEXT,
            created_at TEXT,
            PRIMARY KEY (text_hash, target)
        );

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    # Migrate databases created before the event-location layer.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(articles)")}
    for column in ("event_country", "event_region", "event_places",
                   "event_entities", "event_topics", "event_confidence",
                   "content_type", "content_type_terms", "rss_categories"):
        if column not in existing:
            conn.execute(f"ALTER TABLE articles ADD COLUMN {column} TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_articles_event_country ON articles(event_country)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_articles_event_region ON articles(event_region)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_articles_content_type ON articles(content_type)")
    conn.commit()


def sync_feeds(conn: sqlite3.Connection, feeds: list[dict]) -> None:
    for feed in feeds:
        conn.execute(
            """
            INSERT INTO feeds (id, name, publisher, url, homepage, country, language,
                ownership, kind, category_hint, refresh_minutes, max_items, enabled)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, publisher=excluded.publisher, url=excluded.url,
                homepage=excluded.homepage, country=excluded.country,
                language=excluded.language, ownership=excluded.ownership,
                kind=excluded.kind, category_hint=excluded.category_hint,
                refresh_minutes=excluded.refresh_minutes, max_items=excluded.max_items,
                enabled=excluded.enabled
            """,
            (
                feed["id"], feed.get("name"), feed.get("publisher"), feed.get("url"),
                feed.get("homepage"), feed.get("country"), feed.get("language"),
                feed.get("ownership", "private"), feed.get("kind", "direct"),
                feed.get("category_hint"), int(feed.get("refresh_minutes", 30)),
                int(feed.get("max_items", 40)), 1 if feed.get("enabled", True) else 0,
            ),
        )
    conn.commit()


def feed_states(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {row["id"]: row for row in conn.execute("SELECT * FROM feeds")}


def update_feed_state(
    conn: sqlite3.Connection,
    feed_id: str,
    *,
    status: str,
    error: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    count: int = 0,
) -> None:
    conn.execute(
        """
        UPDATE feeds SET last_fetch_at=?, last_status=?, last_error=?, etag=COALESCE(?, etag),
            last_modified=COALESCE(?, last_modified), last_count=?,
            total_fetched=total_fetched+?
        WHERE id=?
        """,
        (utcnow(), status, error, etag, last_modified, count, count, feed_id),
    )
    conn.commit()


def insert_articles(conn: sqlite3.Connection, articles: list[dict]) -> int:
    new = 0
    for article in articles:
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO articles (
                id, title, summary, url, image_url, feed_id, feed_name, publisher,
                publisher_url, country, region, language, category, category_terms,
                category_scores, ownership, published_at, fetched_at, fingerprint, is_demo,
                event_country, event_region, event_places, event_entities, event_topics,
                event_confidence, content_type, content_type_terms, rss_categories
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                article["id"], article["title"], article.get("summary", ""), article["url"],
                article.get("image_url"), article["feed_id"], article.get("feed_name"),
                article["publisher"], article.get("publisher_url"), article.get("country"),
                article.get("region"), article.get("language"), article.get("category", "other"),
                json.dumps(article.get("category_terms", []), ensure_ascii=False),
                json.dumps(article.get("category_scores", {}), ensure_ascii=False),
                article.get("ownership"), article["published_at"], article["fetched_at"],
                article["fingerprint"], 1 if article.get("is_demo") else 0,
                article.get("event_country"), article.get("event_region"),
                json.dumps(article.get("event_places", []), ensure_ascii=False),
                json.dumps(article.get("event_entities", []), ensure_ascii=False),
                json.dumps(article.get("event_topics", []), ensure_ascii=False),
                article.get("event_confidence"),
                article.get("content_type", "hard"),
                json.dumps(article.get("content_type_terms", []), ensure_ascii=False),
                json.dumps(article.get("rss_categories", []), ensure_ascii=False),
            ),
        )
        if conn.total_changes > before:
            new += 1
    conn.commit()
    return new


def _since(hours: int) -> str:
    hours = max(1, min(int(hours or 24), 24 * 90))
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


_ENTITY_ALIAS_CACHE: dict[str, tuple[str, ...]] | None = None


def _entity_alias_ids(token: str) -> tuple[str, ...]:
    """Map a multilingual actor/org alias to canonical event entity IDs."""
    global _ENTITY_ALIAS_CACHE
    if _ENTITY_ALIAS_CACHE is None:
        data = json.loads(
            (Path(__file__).resolve().parent.parent / "config" / "gazetteer.json")
            .read_text(encoding="utf-8")
        )
        cache: dict[str, set[str]] = {}
        for actor in data.get("actors", []):
            prefix = "ORG" if actor.get("kind") in ("org", "organisation", "organization") else "ACTOR"
            entity_id = f"{prefix}:{actor.get('id', '')}"
            for alias in [actor.get("id", "")] + list(actor.get("aliases", [])):
                key = str(alias).strip().casefold()
                if key:
                    cache.setdefault(key, set()).add(entity_id)
        _ENTITY_ALIAS_CACHE = {key: tuple(sorted(values)) for key, values in cache.items()}
    return _ENTITY_ALIAS_CACHE.get(token.strip().casefold(), ())


def _build_where(
    filters: dict, exclude: str | tuple[str, ...] | None = None
) -> tuple[str, list[Any]]:
    clauses = ["published_at >= ?"]
    params: list[Any] = [_since(filters.get("hours", 24))]
    if filters.get("until"):
        clauses.append("published_at <= ?")
        params.append(filters["until"])
    q = (filters.get("q") or "").strip()
    variants = filters.get("_variants") or []
    search_groups: list[str] = []
    search_params: list[Any] = []

    if q:
        # Every whitespace-separated token must match somewhere. Searching the
        # event JSON makes Chinese place/topic queries work even when the
        # headline is in another language. Actor aliases are expanded to their
        # canonical ACTOR:/ORG: IDs (e.g. 普京 -> ACTOR:PUTIN).
        normalized = q.replace('"', " ").replace("“", " ").replace("”", " ")
        tokens = [token for token in re.split(r"\s+", normalized) if token][:8]
        group_parts: list[str] = []
        group_params: list[Any] = []
        for token in tokens or [q]:
            fields = [
                "title", "summary", "publisher",
                "event_places", "event_entities", "event_topics",
            ]
            like = f"%{token}%"
            token_params = [like] * len(fields)
            for entity_id in _entity_alias_ids(token):
                fields.append("event_entities")
                token_params.append(f"%{entity_id}%")
            group_parts.append("(" + " OR ".join(f"{field} LIKE ?" for field in fields) + ")")
            group_params.extend(token_params)
        if group_parts:
            search_groups.append("(" + " AND ".join(group_parts) + ")")
            search_params.extend(group_params)

    # Cross-language variants broaden the search: each translation may match
    # by its whole phrase, or by all of its significant terms. Variants are
    # ORed together; the original-language clause above remains the precise
    # path.
    for variant in variants:
        text = str(variant.get("text") or "").strip()
        if not text:
            continue
        terms: list[str] = []
        for term in variant.get("terms") or []:
            term = str(term).strip()
            if term and term not in terms:
                terms.append(term)
        terms = terms[:4]
        whole_like = f"%{text}%"
        whole_clause = "(title LIKE ? OR summary LIKE ? OR event_places LIKE ? OR event_topics LIKE ?)"
        parts = [whole_clause]
        variant_params: list[Any] = [whole_like] * 4
        if len(terms) >= 2:
            term_clauses: list[str] = []
            for term in terms:
                like = f"%{term}%"
                term_clauses.append(
                    "(title LIKE ? OR summary LIKE ? OR event_places LIKE ? OR event_topics LIKE ?)"
                )
                variant_params.extend([like] * 4)
            parts.append("(" + " AND ".join(term_clauses) + ")")
        search_groups.append("(" + " OR ".join(parts) + ")")
        search_params.extend(variant_params)

    if search_groups:
        clauses.append("(" + " OR ".join(search_groups) + ")")
        params.extend(search_params)
    geo = "event" if filters.get("geo") == "event" else "source"
    columns = {
        "category": "category",
        "language": "language",
        "publisher": "publisher",
        "region": "event_region" if geo == "event" else "region",
        "country": "event_country" if geo == "event" else "country",
        "content_type": "content_type",
    }
    excluded = {exclude} if isinstance(exclude, str) else set(exclude or ())
    for field in ("category", "content_type", "region", "language", "publisher", "country"):
        value = filters.get(field)
        if value and value != "all" and field not in excluded:
            clauses.append(f"{columns[field]} = ?")
            params.append(value)
    return " AND ".join(clauses), params


def query_articles(conn: sqlite3.Connection, filters: dict, limit: int = 300, offset: int = 0) -> tuple[list[dict], int]:
    where, params = _build_where(filters)
    total = conn.execute(f"SELECT COUNT(*) FROM articles WHERE {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM articles WHERE {where} ORDER BY published_at DESC LIMIT ? OFFSET ?",
        params + [max(1, min(int(limit or 300), 800)), max(0, int(offset or 0))],
    ).fetchall()
    return [dict(row) for row in rows], total


def facet_counts(conn: sqlite3.Connection, filters: dict) -> dict[str, list[dict]]:
    geo = "event" if filters.get("geo") == "event" else "source"
    fields = {
        "category": ("category", 10),
        "region": ("event_region" if geo == "event" else "region", 20),
        "language": ("language", 30),
        "publisher": ("publisher", 600),
        "content_type": ("content_type", 10),
        "country": ("event_country" if geo == "event" else "country", 120),
    }
    result: dict[str, list[dict]] = {}
    for name, (column, limit) in fields.items():
        where, params = _build_where(filters, exclude=name)
        rows = conn.execute(
            f"""
            SELECT {column} AS key, COUNT(*) AS count
            FROM articles WHERE {where} AND {column} IS NOT NULL AND {column} != ''
            GROUP BY {column} ORDER BY count DESC, key ASC LIMIT ?
            """,
            params + [limit],
        ).fetchall()
        result[name] = [{"key": row["key"], "count": row["count"]} for row in rows]
    return result


def kpis(conn: sqlite3.Connection, filters: dict) -> dict:
    where, params = _build_where(filters)
    country_col = "event_country" if filters.get("geo") == "event" else "country"
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS total,
               COUNT(DISTINCT publisher) AS publishers,
               COUNT(DISTINCT language) AS languages,
               COUNT(DISTINCT {country_col}) AS countries,
               COUNT(DISTINCT feed_id) AS feeds,
               MIN(published_at) AS earliest,
               MAX(published_at) AS latest
        FROM articles WHERE {where}
        """,
        params,
    ).fetchone()
    return dict(row)


def search_summary(conn: sqlite3.Connection, filters: dict, limit: int = 6000) -> dict:
    """Aggregate topics/places for the full search result, not just one page."""
    where, params = _build_where(filters)
    rows = conn.execute(
        f"SELECT event_topics, event_places, content_type FROM articles WHERE {where} LIMIT ?",
        params + [limit],
    ).fetchall()
    topics: dict[str, dict] = {}
    places: dict[str, dict] = {}
    types: dict[str, int] = {}
    for row in rows:
        content_type = row["content_type"] or "hard"
        types[content_type] = types.get(content_type, 0) + 1
        for field, bucket in (("event_topics", topics), ("event_places", places)):
            try:
                data = json.loads(row[field] or "[]")
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for entry in data:
                if isinstance(entry, dict):
                    key = str(entry.get("id") or entry.get("label") or "").strip()
                    label = str(entry.get("label") or entry.get("id") or "").strip()
                else:
                    key = label = str(entry).strip()
                if not key:
                    continue
                item = bucket.setdefault(key, {"id": key, "label": label or key, "count": 0})
                if label:
                    item["label"] = label
                item["count"] += 1

    def top(bucket: dict[str, dict], size: int = 8) -> list[dict]:
        return sorted(bucket.values(), key=lambda item: (-item["count"], item["label"]))[:size]

    source_countries = conn.execute(
        f"SELECT COUNT(DISTINCT country) FROM articles WHERE {where}", params
    ).fetchone()[0]
    return {
        "source_countries": source_countries,
        "topics": top(topics),
        "places": top(places),
        "content_types": [
            {"key": key, "count": count}
            for key, count in sorted(types.items(), key=lambda pair: (-pair[1], pair[0]))
        ],
        "sampled": len(rows),
    }


def unlocated_count(conn: sqlite3.Connection, filters: dict) -> int:
    """Articles in the current slice with no event region (event mode only)."""
    if filters.get("geo") != "event":
        return 0
    relaxed = dict(filters)
    relaxed["region"] = "all"
    relaxed["country"] = "all"
    where, params = _build_where(relaxed)
    return conn.execute(
        f"SELECT COUNT(*) FROM articles WHERE {where} AND event_region IS NULL",
        params,
    ).fetchone()[0]


def hourly_volume(conn: sqlite3.Connection, filters: dict) -> list[dict]:
    where, params = _build_where(filters)
    rows = conn.execute(
        f"""
        SELECT substr(published_at, 1, 13) || ':00:00Z' AS hour, COUNT(*) AS count
        FROM articles WHERE {where}
        GROUP BY hour ORDER BY hour ASC
        """,
        params,
    ).fetchall()
    return [{"t": row["hour"], "count": row["count"]} for row in rows]


def top_publishers(conn: sqlite3.Connection, filters: dict, limit: int = 10) -> list[dict]:
    where, params = _build_where(filters)
    rows = conn.execute(
        f"""
        SELECT publisher AS name, country, COUNT(*) AS count
        FROM articles WHERE {where}
        GROUP BY publisher, country ORDER BY count DESC LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    return [dict(row) for row in rows]


def meta_get(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def count_articles(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]


def purge_old(conn: sqlite3.Connection, days: int = 60) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute("DELETE FROM articles WHERE published_at < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def feed_health(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) AS enabled,
               SUM(CASE WHEN enabled=1 AND last_status IN ('ok','not_modified','empty') THEN 1 ELSE 0 END) AS ok,
               SUM(CASE WHEN enabled=1 AND last_status='error' THEN 1 ELSE 0 END) AS errors
        FROM feeds
        """
    ).fetchone()
    return dict(row)
