#!/usr/bin/env python3
"""Local web server for the Global News Timeline.

Standard library only. Serves the static UI and a small JSON API, and starts a
background RSS ingestion scheduler on launch.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import mimetypes
import os
import socket
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from db import (
    connect,
    count_articles,
    facet_counts,
    feed_health,
    hourly_volume,
    init_db,
    kpis,
    meta_get,
    query_articles,
    search_summary,
    sync_feeds,
    top_publishers,
    unlocated_count,
)
from ingest import load_config, refresh_async, scheduler_loop
from query_expand import expand_search
from taxonomy import (
    CATEGORIES,
    COUNTRIES,
    LANGUAGES,
    REGIONS,
    category_label,
    content_type_label,
    country_label,
    language_label,
    ownership_label,
    region_label,
)
from textutil import cluster_articles, diversify
from translate import translate

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
VERSION = "1.5.1"
LOG = logging.getLogger("server")

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
NO_FETCH = os.environ.get("NEWS_NO_FETCH", "").lower() in ("1", "true", "yes")

DEFAULT_CSP = (
    "default-src 'self'; img-src 'self' https: data:; "
    "style-src 'self' 'unsafe-inline'; script-src 'self'; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'"
)
RECEIVER_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; "
    "script-src 'unsafe-inline'; img-src data:; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def _iso_day_ago(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def status_payload(conn) -> dict:
    health = feed_health(conn)
    total = count_articles(conn)
    day_count = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE published_at >= ?", (_iso_day_ago(24),)
    ).fetchone()[0]
    import ingest
    import translate as translate_module

    last_at = meta_get(conn, "last_ingest_at")
    last_new = meta_get(conn, "last_new_count", "0")
    last_duration = meta_get(conn, "last_duration_seconds", "0")
    return {
        "version": VERSION,
        "server_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "refreshing": bool(ingest._refreshing),
        "last_ingest_at": last_at,
        "last_new_count": int(last_new or 0),
        "last_duration_seconds": float(last_duration or 0),
        "articles_total": total,
        "articles_24h": day_count,
        "feeds": {
            "total": health.get("total") or 0,
            "enabled": health.get("enabled") or 0,
            "ok": health.get("ok") or 0,
            "errors": health.get("errors") or 0,
        },
        "translation": {
            "free_only": translate_module.TRANSLATE_FREE_ONLY,
            "providers": [name for name, _ in translate_module._chain()],
        },
    }


def parse_filters(query: dict) -> dict:
    def one(key: str, default: str) -> str:
        value = (query.get(key) or [default])[0].strip()
        return value or default

    try:
        hours = int(one("hours", "24"))
    except ValueError:
        hours = 24
    if hours not in (24, 72, 168, 720):
        hours = 24

    category = one("category", "all")
    if category not in CATEGORIES and category != "all":
        category = "all"
    region = one("region", "all")
    if region not in REGIONS and region != "all":
        region = "all"
    language = one("language", "all")
    if language not in LANGUAGES and language != "all":
        language = "all"
    country = one("country", "all").upper()
    if country != "ALL" and (len(country) != 2 or not country.isalpha()):
        country = "all"
    elif country == "ALL":
        country = "all"
    geo = one("geo", "event")
    if geo not in ("event", "source"):
        geo = "event"
    content_type = one("content_type", "all")
    if content_type not in ("hard", "analysis", "opinion"):
        content_type = "all"

    return {
        "hours": hours,
        "geo": geo,
        "content_type": content_type,
        "category": category,
        "region": region,
        "language": language,
        "publisher": one("publisher", "all")[:120],
        "country": country if country != "all" else "all",
        "q": one("q", "")[:120],
    }


def decorate(item: dict) -> dict:
    item["category_label"] = category_label(item.get("category", "other"))
    item["language_label"] = language_label(item.get("language", ""))
    item["region_label"] = region_label(item.get("region", "other"))
    item["country_label"] = country_label(item.get("country"))
    item["ownership_label"] = ownership_label(item.get("ownership"))
    item["content_type_label"] = content_type_label(item.get("content_type"))
    item["coverage"] = item.get("coverage", 1)
    item["related"] = item.get("related", [])
    item["event_country_label"] = (
        country_label(item["event_country"]) if item.get("event_country") else ""
    )
    item["event_region_label"] = (
        region_label(item["event_region"]) if item.get("event_region") else ""
    )
    for field in ("event_places", "event_entities", "event_topics",
                  "content_type_terms", "rss_categories"):
        try:
            item[field] = json.loads(item.get(field) or "[]")
        except Exception:
            item[field] = []
    item["event_confidence"] = item.get("event_confidence") or "none"
    try:
        item["category_terms"] = json.loads(item.get("category_terms") or "[]")
    except Exception:
        item["category_terms"] = []
    item.pop("category_scores", None)
    return item


def query_payload(conn, filters: dict, limit: int, offset: int) -> dict:
    expansion = expand_search(filters) if filters.get("q") else None
    items, total = query_articles(conn, filters, limit=limit, offset=offset)
    items = [decorate(dict(row)) for row in items]
    cluster_articles(items)
    items = diversify(items)

    facets = facet_counts(conn, filters)
    for name, facet in facets.items():
        for entry in facet:
            key = entry["key"]
            if name == "category":
                entry["label"] = category_label(key)
            elif name == "region":
                entry["label"] = region_label(key)
            elif name == "language":
                entry["label"] = language_label(key)
            elif name == "content_type":
                entry["label"] = content_type_label(key)
            elif name == "country":
                info = COUNTRIES.get(key, {})
                entry["label"] = country_label(key)
                entry["region"] = info.get("region", "other")
                entry["region_label"] = region_label(info.get("region", "other"))
            else:
                entry["label"] = key
    kpi = kpis(conn, filters)
    hourly = hourly_volume(conn, filters)
    search = None
    if filters.get("q"):
        search = search_summary(conn, filters)
        search["q"] = filters["q"]
        search["tokens"] = [
            token
            for token in filters["q"].replace('"', " ").replace("“", " ").replace("”", " ").split()
            if token
        ][:8]
        for entry in search.get("content_types", []):
            entry["label"] = content_type_label(entry["key"])
        search["cross_language"] = expansion
    public_filters = {key: value for key, value in filters.items() if not key.startswith("_")}
    return {
        "search": search,
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "facets": facets,
        "kpis": kpi,
        "hourly": hourly,
        "top_publishers": top_publishers(conn, filters, 10),
        "unlocated": unlocated_count(conn, filters),
        "filters": public_filters,
        "status": status_payload(conn),
    }


def feeds_payload(conn) -> dict:
    rows = conn.execute(
        """
        SELECT id, name, publisher, homepage, country, language, ownership, kind,
               refresh_minutes, last_fetch_at, last_status, last_error, last_count,
               total_fetched, enabled
        FROM feeds ORDER BY kind ASC, country ASC, name ASC
        """
    ).fetchall()
    feeds = []
    for row in rows:
        item = dict(row)
        item["country_label"] = country_label(item.get("country"))
        item["language_label"] = language_label(item.get("language"))
        item["ownership_label"] = ownership_label(item.get("ownership"))
        item["enabled"] = bool(item.get("enabled"))
        feeds.append(item)
    return {
        "feeds": feeds,
        "total": len(feeds),
        "ok": sum(1 for f in feeds if f["last_status"] in ("ok", "not_modified", "empty")),
        "errors": sum(1 for f in feeds if f["last_status"] == "error"),
    }


def _json_labels(raw) -> str:
    try:
        data = json.loads(raw or "[]") if isinstance(raw, str) else (raw or [])
    except Exception:
        return ""
    labels = []
    for item in data:
        if isinstance(item, dict):
            labels.append(str(item.get("label") or item.get("id") or ""))
        else:
            labels.append(str(item))
    return " | ".join(x for x in labels if x)


def export_csv(conn, filters: dict) -> tuple[bytes, str]:
    if filters.get("q"):
        expand_search(filters)
    items, _ = query_articles(conn, filters, limit=5000, offset=0)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        ["published_at", "title", "summary", "publisher", "country", "region",
         "event_country", "event_region", "event_confidence", "event_places",
         "event_topics", "language", "category", "content_type",
         "content_type_terms", "ownership", "url"]
    )
    for item in items:
        writer.writerow(
            [
                item.get("published_at", ""),
                item.get("title", ""),
                item.get("summary", ""),
                item.get("publisher", ""),
                item.get("country", ""),
                item.get("region", ""),
                item.get("event_country", ""),
                item.get("event_region", ""),
                item.get("event_confidence", ""),
                _json_labels(item.get("event_places")),
                _json_labels(item.get("event_topics")),
                item.get("language", ""),
                item.get("category", ""),
                item.get("content_type", "hard"),
                _json_labels(item.get("content_type_terms")),
                item.get("ownership", ""),
                item.get("url", ""),
            ]
        )
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return ("﻿" + buffer.getvalue()).encode("utf-8"), f"global-news-{stamp}.csv"


class Handler(BaseHTTPRequestHandler):
    server_version = "GlobalNewsTimeline/" + VERSION
    protocol_version = "HTTP/1.1"

    def _send(
        self,
        code: int,
        body: bytes,
        content_type: str,
        extra: dict | None = None,
        csp: str | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", csp or DEFAULT_CSP)
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict, code: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})

    def _error(self, code: int, message: str) -> None:
        self._json({"ok": False, "error": message}, code=code)

    def _static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        rel = path.lstrip("/")
        target = (WEB / rel).resolve()
        if WEB.resolve() not in target.parents and target != WEB.resolve():
            self._error(403, "Forbidden")
            return
        if not target.is_file():
            self._error(404, "Not found")
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix == ".js":
            ctype = "application/javascript; charset=utf-8"
        elif target.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif target.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        body = target.read_bytes()
        self._send(200, body, ctype, {"Cache-Control": "no-cache"})

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/api/health":
            conn = connect()
            try:
                self._json({"ok": True, "version": VERSION, "articles": count_articles(conn)})
            finally:
                conn.close()
            return
        if path == "/api/status":
            conn = connect()
            try:
                self._json(status_payload(conn))
            finally:
                conn.close()
            return
        if path == "/api/feeds":
            conn = connect()
            try:
                self._json(feeds_payload(conn))
            finally:
                conn.close()
            return
        if path in ("/api/query", "/api/articles"):
            conn = connect()
            try:
                filters = parse_filters(query)
                try:
                    limit = max(1, min(int((query.get("limit") or ["240"])[0]), 600))
                    offset = max(0, int((query.get("offset") or ["0"])[0]))
                except ValueError:
                    limit, offset = 240, 0
                self._json(query_payload(conn, filters, limit, offset))
            finally:
                conn.close()
            return
        if path == "/api/export.csv":
            conn = connect()
            try:
                filters = parse_filters(query)
                body, filename = export_csv(conn, filters)
                self._send(
                    200, body, "text/csv; charset=utf-8",
                    {"Content-Disposition": f'attachment; filename="{filename}"',
                     "Cache-Control": "no-store"},
                )
            finally:
                conn.close()
            return
        if path == "/p2p-receiver.html":
            target = WEB / "p2p-receiver.html"
            if not target.is_file():
                self._error(404, "Not found")
                return
            self._send(
                200,
                target.read_bytes(),
                "text/html; charset=utf-8",
                {"Cache-Control": "no-cache"},
                csp=RECEIVER_CSP,
            )
            return
        if path.startswith("/api/"):
            self._error(404, "Unknown API endpoint")
            return
        self._static(path)

    def do_HEAD(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            ctype = "text/html; charset=utf-8"
        elif path.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif path.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif path.endswith(".svg"):
            ctype = "image/svg+xml"
        elif path == "/api/health":
            ctype = "application/json; charset=utf-8"
        elif path == "/p2p-receiver.html":
            ctype = "text/html; charset=utf-8"
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            RECEIVER_CSP if path == "/p2p-receiver.html" else DEFAULT_CSP,
        )
        self.end_headers()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        if length > 64_000:
            self._error(413, "Request body too large")
            return
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = {}

        if path == "/api/refresh":
            force = bool(payload.get("force", True))
            self._json({"ok": True, **refresh_async(force=force)})
            return
        if path == "/api/translate":
            conn = connect()
            try:
                result = translate(
                    conn,
                    str(payload.get("text", "")),
                    str(payload.get("target", "zh")),
                    str(payload.get("source") or "") or None,
                )
                self._json(result, 200 if result.get("ok") else 503)
            finally:
                conn.close()
            return
        self._error(404, "Unknown API endpoint")

    def log_message(self, fmt: str, *args) -> None:
        if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            LOG.warning("%s - %s", self.address_string(), fmt % args)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    config = load_config()
    conn = connect()
    init_db(conn)
    sync_feeds(conn, config["feeds"])
    conn.close()

    if not NO_FETCH:
        thread = threading.Thread(target=scheduler_loop, daemon=True, name="rss-scheduler")
        thread.start()
    else:
        LOG.info("NEWS_NO_FETCH set; background ingestion disabled")

    port = PORT
    server = None
    for candidate in range(PORT, PORT + 20):
        try:
            server = ThreadingHTTPServer((HOST, candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    if server is None:
        LOG.error("No free port in %s-%s", PORT, PORT + 19)
        return 1

    print()
    print("  MERIDIAN / GLOBAL NEWS TIMELINE")
    print(f"  http://{HOST}:{port}")
    print(f"  database: {ROOT / 'data' / 'news.db'}")
    print("  Ctrl+C to stop")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping…")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
