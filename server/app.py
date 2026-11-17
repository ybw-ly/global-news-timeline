#!/usr/bin/env python3
"""Local web server for the Global News Timeline.

Standard library only. Serves the static UI and a small JSON API, and starts a
background RSS ingestion scheduler on launch.
"""
from __future__ import annotations

import csv
import hmac
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

import article_meta
import customization
from elections import (
    default_election,
    fetch_election_results,
    get_election,
    list_elections,
)
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
from query_expand import SEARCH_RELAX_MIN, expand_search
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
from translation_specs import detect_key_hints

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
VERSION = "1.16.0"
LOG = logging.getLogger("server")

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
NO_FETCH = os.environ.get("NEWS_NO_FETCH", "").lower() in ("1", "true", "yes")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()

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
        "SELECT COUNT(*) FROM articles WHERE published_at >= ? AND COALESCE(filtered, 0) = 0",
        (_iso_day_ago(24),),
    ).fetchone()[0]
    filtered_total = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE COALESCE(filtered, 0) = 1"
    ).fetchone()[0]
    import ingest
    import translate as translate_module

    last_at = meta_get(conn, "last_ingest_at")
    last_new = meta_get(conn, "last_new_count", "0")
    last_filtered = meta_get(conn, "last_filtered_count", "0")
    last_duration = meta_get(conn, "last_duration_seconds", "0")
    return {
        "version": VERSION,
        "server_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "refreshing": bool(ingest._refreshing),
        "last_ingest_at": last_at,
        "last_new_count": int(last_new or 0),
        "last_filtered_count": int(last_filtered or 0),
        "last_duration_seconds": float(last_duration or 0),
        "articles_total": total,
        "articles_24h": day_count,
        "articles_filtered": filtered_total,
        "feeds": {
            "total": health.get("total") or 0,
            "enabled": health.get("enabled") or 0,
            "ok": health.get("ok") or 0,
            "errors": health.get("errors") or 0,
        },
        "translation": {
            "provider": translate_module.settings()["provider"],
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
    item["content_type_label"] = (
        "预测市场" if item.get("ownership") == "market"
        else content_type_label(item.get("content_type"))
    )
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


def _search_score(item: dict, q: str, variants: list[dict]) -> int:
    """Cheap relevance score: title hits beat summary/event hits.

    Recency remains the tie-breaker because the SQL rows arrive newest-first
    and Python's sort is stable.
    """
    title = str(item.get("title") or "").casefold()
    summary = str(item.get("summary") or "").casefold()
    event_text = " ".join(
        str(item.get(field) or "")
        for field in ("event_places", "event_entities", "event_topics")
    ).casefold()
    score = 0
    needle = q.casefold()
    if needle and needle in title:
        score += 120
    elif needle and needle in summary:
        score += 35
    tokens = [token for token in needle.split() if len(token) > 1]
    for token in tokens:
        if token in title:
            score += 24
        elif token in summary:
            score += 7
        elif token in event_text:
            score += 4
    for variant in variants:
        text = str(variant.get("text") or "").casefold()
        if len(text) > 2 and text in title:
            score += 10
        for term in (variant.get("terms") or [])[:4]:
            value = str(term or "").casefold()
            if len(value) > 1 and value in title:
                score += 3
    return score


def query_payload(conn, filters: dict, limit: int, offset: int) -> dict:
    expansion = expand_search(filters) if filters.get("q") else None
    strict_total = None
    items, total = query_articles(conn, filters, limit=limit, offset=offset)
    if filters.get("q") and not filters.get("_relaxed") and total < SEARCH_RELAX_MIN:
        strict_total = total
        relaxed_filters = dict(filters)
        relaxed_filters["_relaxed"] = True
        relaxed_items, relaxed_total = query_articles(
            conn, relaxed_filters, limit=limit, offset=offset
        )
        if relaxed_total > total:
            filters = relaxed_filters
            items, total = relaxed_items, relaxed_total
            if expansion is not None:
                expansion["relaxed"] = True
                expansion["strict_total"] = strict_total
                expansion["relaxed_total"] = relaxed_total
    if expansion is not None and expansion.get("strict_total") is None:
        expansion["strict_total"] = total
    items = [decorate(dict(row)) for row in items]
    if filters.get("q"):
        q_value = filters.get("q") or ""
        variants = filters.get("_variants") or []
        items.sort(key=lambda item: _search_score(item, q_value, variants), reverse=True)
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

    def _admin_allowed(self) -> bool:
        if ADMIN_TOKEN:
            provided = self.headers.get("X-Admin-Token", "")
            return hmac.compare_digest(provided, ADMIN_TOKEN)
        client = (self.client_address[0] or "").lower()
        return client in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

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
        if path == "/api/elections":
            default = default_election()
            self._json(
                {
                    "ok": True,
                    "default": default.get("id") if default else None,
                    "elections": list_elections(),
                }
            )
            return
        if path.startswith("/api/elections/"):
            parts = [part for part in path.split("/") if part]
            if len(parts) in (3, 4):
                election_id = parts[2]
                election = get_election(election_id)
                if not election:
                    self._error(404, "Unknown election")
                    return
                if len(parts) == 3:
                    self._json({"ok": True, "election": election})
                    return
                if parts[3] == "results":
                    scope = (query.get("scope") or ["br"])[0]
                    self._json(fetch_election_results(election_id, scope))
                    return
            self._error(404, "Not found")
            return
        if path == "/api/customize/state":
            payload = customization.state()
            payload["version"] = VERSION
            payload["admin"] = {
                "required": bool(ADMIN_TOKEN),
                "authorized": self._admin_allowed(),
            }
            self._json({"ok": True, **payload})
            return
        if path == "/api/customize/ui":
            self._json({"ok": True, "ui": customization.get_ui()})
            return
        if path == "/api/customize/export":
            if ADMIN_TOKEN and not self._admin_allowed():
                self._error(403, "需要管理员令牌（ADMIN_TOKEN）")
                return
            bundle = customization.export_bundle(include_secrets=False)
            body = json.dumps(bundle, ensure_ascii=False, indent=2).encode("utf-8")
            self._send(
                200, body, "application/json; charset=utf-8",
                {
                    "Content-Disposition": 'attachment; filename="global-news-timeline-customization.json"',
                    "Cache-Control": "no-store",
                },
            )
            return
        if path.startswith("/api/customize/config/"):
            if ADMIN_TOKEN and not self._admin_allowed():
                self._error(403, "需要管理员令牌（ADMIN_TOKEN）")
                return
            name = path.rsplit("/", 1)[-1]
            try:
                self._json({"ok": True, **customization.describe(name)})
            except customization.ConfigError as exc:
                self._error(404, str(exc))
            return
        # Backwards compatibility for the original Brazil-only endpoint.
        if path == "/api/brazil/results":
            scope = (query.get("scope") or ["br"])[0]
            self._json(fetch_election_results("brazil-2026", scope))
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
        if length > 8_000_000:
            self._error(413, "Request body too large")
            return
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = {}

        if path == "/api/article/description":
            if not self._admin_allowed():
                self._error(403, "需要管理员令牌（ADMIN_TOKEN）")
                return
            url = str(payload.get("url") or "").strip()
            if not url:
                self._error(400, "url is required")
                return
            result = article_meta.fetch_description(url)
            self._json(result, 200 if result.get("ok") else 502)
            return

        if path.startswith("/api/customize/"):
            if not self._admin_allowed():
                self._error(403, "需要管理员令牌（ADMIN_TOKEN）")
                return
            try:
                if path == "/api/customize/ui":
                    ui = customization.save_ui(payload.get("ui", payload))
                    self._json({"ok": True, "ui": ui})
                    return
                if path == "/api/customize/runtime":
                    runtime = customization.save_runtime(payload)
                    self._json({"ok": True, "runtime": runtime})
                    return
                if path == "/api/customize/detect-key":
                    key = str(payload.get("key") or "")[:512]
                    self._json({"ok": True, "hints": detect_key_hints(key)})
                    return
                if path == "/api/customize/reload":
                    customization.reset_runtime_caches()
                    self._json({"ok": True})
                    return
                if path == "/api/customize/reset-all":
                    customization.reset_all()
                    self._json({"ok": True})
                    return
                if path == "/api/customize/import":
                    bundle = payload.get("bundle", payload)
                    result = customization.import_bundle(
                        bundle, bool(payload.get("merge", True))
                    )
                    self._json({"ok": True, **result})
                    return
                if path.startswith("/api/customize/config/"):
                    name = path.rsplit("/", 1)[-1]
                    result = customization.save_config(name, payload.get("data"))
                    self._json({"ok": True, **result})
                    return
                if path.startswith("/api/customize/reset/"):
                    name = path.rsplit("/", 1)[-1]
                    result = customization.reset_config(name)
                    self._json({"ok": True, **result})
                    return
                if path == "/api/customize/feeds/test":
                    feed = payload.get("feed")
                    if not isinstance(feed, dict) or not feed.get("url"):
                        self._error(400, "feed.url is required")
                        return
                    import ingest

                    result = ingest._fetch(
                        feed, None, 15, "GlobalNewsTimeline/1.0", True
                    )
                    items = result.get("items") or []
                    self._json(
                        {
                            "ok": result.get("status") in ("ok", "empty", "not_modified"),
                            "status": result.get("status"),
                            "seconds": result.get("seconds"),
                            "error": result.get("error"),
                            "count": len(items),
                            "items": [
                                {"title": item.get("title"), "url": item.get("url")}
                                for item in items[:8]
                            ],
                        }
                    )
                    return
            except customization.ConfigError as exc:
                self._error(400, str(exc))
                return
            except Exception as exc:
                self._error(500, f"配置操作失败：{str(exc)[:180]}")
                return
            self._error(404, "Unknown customization endpoint")
            return

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
                    fast=bool(payload.get("fast", False)),
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
