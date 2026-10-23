"""RSS/Atom ingestion pipeline with conditional GET and polite scheduling."""
from __future__ import annotations

import concurrent.futures
import gzip
import hashlib
import html
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from classifier import Classifier
from contenttype import classifier as content_classifier
from eventgraph import graph as event_graph
from db import (
    connect,
    feed_states,
    init_db,
    insert_articles,
    meta_get,
    meta_set,
    purge_old,
    sync_feeds,
    update_feed_state,
    utcnow,
)
from taxonomy import country_from_url, region_of, script_matches
from textutil import (
    article_id,
    canonical_url,
    clean_title,
    ensure_http,
    fingerprint,
    strip_html,
)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "feeds.json"
LOG = logging.getLogger("ingest")

_lock = threading.Lock()
_refreshing = False
_last_result: dict[str, Any] = {}

_IMAGE_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)', re.IGNORECASE)


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _first_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in node.iter():
        if _local(child.tag) in names and (child.text or "").strip():
            return (child.text or "").strip()
    return ""


def _first_attr(node: ET.Element, tag: str, attr: str) -> str:
    for child in node.iter():
        if _local(child.tag) == tag and child.get(attr):
            return child.get(attr, "")
    return ""


def _parse_date(value: str) -> str:
    value = (value or "").strip()
    now = datetime.now(timezone.utc)
    dt: datetime | None = None
    if value:
        try:
            dt = parsedate_to_datetime(value)
        except Exception:
            dt = None
        if dt is None:
            cleaned = value.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(cleaned)
            except Exception:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        dt = datetime.strptime(value, fmt)
                        break
                    except Exception:
                        continue
    if dt is None:
        dt = now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if dt.year < 2000 or dt > now + timedelta(minutes=15):
        dt = now
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_image(item: ET.Element, description: str) -> str | None:
    for child in item.iter():
        tag = _local(child.tag)
        if tag in ("thumbnail", "content", "enclosure"):
            url = child.get("url") or child.get("href")
            media_type = (child.get("type") or "").lower()
            if url and (not media_type or media_type.startswith("image")):
                return ensure_http(url)
    match = _IMAGE_RE.search(description or "")
    if match:
        return ensure_http(html.unescape(match.group(1)))
    return None


def parse_feed(data: bytes, feed: dict) -> list[dict]:
    root = ET.fromstring(data)
    is_atom = root.tag.lower().endswith("feed")
    nodes = [n for n in root.iter() if _local(n.tag) in ("item", "entry")]
    publisher = feed.get("publisher") or feed.get("name") or feed["id"]
    kind = feed.get("kind", "direct")
    raw_items: list[dict] = []
    now = datetime.now(timezone.utc)

    for node in nodes:
        title = clean_title(_first_text(node, ("title",)))
        if not title:
            continue
        link = ""
        for child in node.iter():
            if _local(child.tag) != "link":
                continue
            href = child.get("href") or (child.text or "").strip()
            rel = (child.get("rel") or "alternate").lower()
            if href and (not link or rel == "alternate"):
                link = href
        if not link:
            link = _first_text(node, ("guid", "id"))
        link = ensure_http(link)
        if not link:
            continue

        date_raw = _first_text(node, ("pubdate", "published", "updated", "date"))
        published_at = _parse_date(date_raw)

        description = _first_text(node, ("description", "summary", "content", "encoded"))
        source_name = _first_text(node, ("source",))
        source_url = _first_attr(node, "source", "url")

        item_publisher = publisher
        item_publisher_url = feed.get("homepage")
        if kind == "aggregator":
            if source_name:
                item_publisher = clean_title(source_name)
                item_publisher_url = ensure_http(source_url) or item_publisher_url
                suffix = f" - {item_publisher}"
                if title.endswith(suffix):
                    title = title[: -len(suffix)].rstrip()
            else:
                # Google News appends " - Publisher" to headlines.
                match = re.search(r"\s[-–—]\s([^-–—]{2,80})$", title)
                if match:
                    item_publisher = match.group(1).strip()
                    title = title[: match.start()].strip()

        if kind == "aggregator":
            summary = ""
        else:
            summary = strip_html(description, 360).strip()
            if summary.lower() in {"none", "null", "n/a", "undefined", "-"}:
                summary = ""
            if summary.lower().startswith(title.lower()):
                summary = summary[len(title):].lstrip(" .:—-–")

        image_url = _extract_image(node, description)
        categories = []
        for child in node.iter():
            if _local(child.tag) == "category":
                term = child.get("term") or (child.text or "").strip()
                if term and term not in categories:
                    categories.append(term)
        raw_items.append(
            {
                "title": title,
                "categories": categories,
                "url": link,
                "published_at": published_at,
                "summary": summary,
                "publisher": clean_title(item_publisher) or publisher,
                "publisher_url": item_publisher_url,
                "image_url": image_url,
            }
        )

    # Keep only recent items, newest first.
    cutoff = (now - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw_items = [item for item in raw_items if item["published_at"] >= cutoff]
    raw_items.sort(key=lambda item: item["published_at"], reverse=True)
    return raw_items[: int(feed.get("max_items", 40))]


def _fetch(
    feed: dict, state: dict | None, timeout: int, user_agent: str, force: bool
) -> dict:
    url = feed["url"]
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Language": "en,*;q=0.5",
        "Accept-Encoding": "gzip, deflate",
    }
    if state and not force:
        if state.get("etag"):
            headers["If-None-Match"] = state["etag"]
        if state.get("last_modified"):
            headers["If-Modified-Since"] = state["last_modified"]

    started = time.time()
    data: bytes | None = None
    etag = last_modified = None
    last_error = None

    for attempt in range(2):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read(4 * 1024 * 1024)
                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
                encoding = (response.headers.get("Content-Encoding") or "").lower()
            if encoding == "gzip" or data[:2] == bytes([0x1f, 0x8b]):
                data = gzip.decompress(data)
            elif encoding == "deflate":
                data = zlib.decompress(data)
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return {
                    "feed": feed, "status": "not_modified", "items": [], "etag": None,
                    "last_modified": None, "error": None,
                    "seconds": round(time.time() - started, 1),
                }
            last_error = f"HTTP {exc.code}"
            if 500 <= exc.code < 600 and attempt == 0:
                time.sleep(1.5)
                continue
            break
        except Exception as exc:
            last_error = str(exc)[:180]
            if attempt == 0:
                time.sleep(1.5)
                continue
            break

    if data is None:
        return {
            "feed": feed, "status": "error", "items": [], "etag": None,
            "last_modified": None, "error": last_error,
            "seconds": round(time.time() - started, 1),
        }

    try:
        items = parse_feed(data, feed)
    except Exception as exc:
        return {
            "feed": feed, "status": "error", "items": [], "etag": None,
            "last_modified": None, "error": f"parse: {exc}"[:180],
            "seconds": round(time.time() - started, 1),
        }
    return {
        "feed": feed,
        "status": "ok" if items else "empty",
        "items": items,
        "etag": etag,
        "last_modified": last_modified,
        "error": None,
        "seconds": round(time.time() - started, 1),
    }


def _due(feed: dict, state: dict | None, now: datetime) -> bool:
    if state is None or not state.get("last_fetch_at"):
        return True
    try:
        last = datetime.strptime(state["last_fetch_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except Exception:
        return True
    minutes = max(15, int(feed.get("refresh_minutes", 30)))
    jitter = int(hashlib.sha1(feed["id"].encode()).hexdigest()[:4], 16) % 90
    if state.get("last_status") == "error":
        # Retry a failed source soon instead of waiting another full interval.
        minutes = 10
    return now >= last + timedelta(minutes=minutes, seconds=jitter)


def build_article(
    raw: dict, feed: dict, classifier: Classifier, eg=None, ctype=None
) -> dict:
    language = feed.get("language") or "en"
    category = classifier.classify(
        raw["title"], raw.get("summary", ""), language, feed.get("category_hint")
    )
    country = feed.get("country")
    publisher_url = raw.get("publisher_url")
    if feed.get("kind") == "aggregator":
        country = country_from_url(publisher_url, country)
    if feed.get("kind") == "aggregator" and not script_matches(raw["title"], language):
        return None
    eg = eg or event_graph()
    event = eg.extract(raw["title"], raw.get("summary", ""))
    ctype = ctype or content_classifier()
    content = ctype.classify(
        raw["title"], raw.get("summary", ""), raw["url"],
        raw.get("categories", []), language, feed.get("content_hint"),
    )
    return {
        "id": article_id(raw["url"], raw["title"]),
        "title": raw["title"],
        "summary": raw.get("summary", ""),
        "url": canonical_url(raw["url"]),
        "image_url": raw.get("image_url"),
        "feed_id": feed["id"],
        "feed_name": feed.get("name"),
        "publisher": raw.get("publisher") or feed.get("publisher") or feed["id"],
        "publisher_url": publisher_url,
        "country": country,
        "region": region_of(country),
        "language": language,
        "category": category["category"],
        "category_terms": category["terms"],
        "category_scores": category["scores"],
        "ownership": feed.get("ownership", "private"),
        "published_at": raw["published_at"],
        "fingerprint": fingerprint(raw["title"]),
        "fetched_at": utcnow(),
        "event_country": event["event_country"],
        "event_region": event["event_region"],
        "event_places": event["event_places"],
        "event_entities": event["event_entities"],
        "event_topics": event["event_topics"],
        "event_confidence": event["event_confidence"],
        "content_type": content["content_type"],
        "content_type_terms": content["content_type_terms"],
        "rss_categories": raw.get("categories", []),
    }


def refresh(force: bool = False, only_ids: list[str] | None = None) -> dict:
    global _refreshing, _last_result
    if not _lock.acquire(blocking=False):
        return {"running": True, "message": "A refresh is already running"}
    _refreshing = True
    started = time.time()
    conn = None
    try:
        config = load_config()
        feeds = [f for f in config["feeds"] if f.get("enabled", True)]
        if only_ids:
            feeds = [f for f in feeds if f["id"] in set(only_ids)]
        settings = config.get("settings", {})
        timeout = int(settings.get("request_timeout", 20))
        user_agent = settings.get("user_agent", "GlobalNewsTimeline/1.0")

        conn = connect()
        init_db(conn)
        sync_feeds(conn, config["feeds"])
        states = {key: dict(value) for key, value in feed_states(conn).items()}
        now = datetime.now(timezone.utc)
        due = [feed for feed in feeds if force or _due(feed, states.get(feed["id"]), now)]

        if due:
            LOG.info("refresh start: %s/%s feeds due", len(due), len(feeds))
        results: list[dict] = []
        if due:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                futures = [
                    pool.submit(_fetch, feed, states.get(feed["id"]), timeout, user_agent, force)
                    for feed in due
                ]
                for future in concurrent.futures.as_completed(futures):
                    results.append(future.result())

        classifier = Classifier()
        eg = event_graph()
        ctype = content_classifier()
        total_new = 0
        total_items = 0
        ok = errors = 0
        for result in results:
            feed = result["feed"]
            items = result["items"]
            parsed = [
                article
                for article in (build_article(item, feed, classifier, eg, ctype) for item in items)
                if article is not None
            ]
            new = insert_articles(conn, parsed)
            total_new += new
            total_items += len(parsed)
            update_feed_state(
                conn,
                feed["id"],
                status=result["status"],
                error=result["error"],
                etag=result["etag"],
                last_modified=result["last_modified"],
                count=len(parsed),
            )
            if result["status"] in ("ok", "empty", "not_modified"):
                ok += 1
            else:
                errors += 1
            LOG.info(
                "%-22s %-12s items=%-3s new=%-3s %.1fs %s",
                feed["id"], result["status"], len(parsed), new, result["seconds"],
                result["error"] or "",
            )

        duration = round(time.time() - started, 1)
        if results:
            meta_set(conn, "last_ingest_at", utcnow())
            meta_set(conn, "last_new_count", str(total_new))
            meta_set(conn, "last_item_count", str(total_items))
            meta_set(conn, "last_duration_seconds", str(duration))
        else:
            meta_set(conn, "last_check_at", utcnow())
        last_purge = meta_get(conn, "last_purge_at")
        if not last_purge or last_purge < (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"):
            purge_old(conn, 60)
            meta_set(conn, "last_purge_at", utcnow())

        _last_result = {
            "at": utcnow(),
            "feeds": len(results),
            "ok": ok,
            "errors": errors,
            "items": total_items,
            "new": total_new,
            "seconds": duration,
        }
        if results:
            LOG.info("refresh done: %s", _last_result)
        return _last_result
    except Exception as exc:
        LOG.exception("refresh failed")
        _last_result = {"at": utcnow(), "error": str(exc)}
        return _last_result
    finally:
        if conn is not None:
            conn.close()
        _refreshing = False
        _lock.release()


def refresh_async(force: bool = False) -> dict:
    if _refreshing:
        return {"running": True, "message": "A refresh is already running"}
    thread = threading.Thread(target=refresh, kwargs={"force": force}, daemon=True)
    thread.start()
    return {"running": True, "message": "Refresh started"}


def scheduler_loop(stop_event: threading.Event | None = None) -> None:
    stop_event = stop_event or threading.Event()
    # First run immediately, then check every 45 seconds.
    time.sleep(1.0)
    refresh(force=False)
    while not stop_event.wait(45):
        try:
            refresh(force=False)
        except Exception:
            LOG.exception("scheduler iteration failed")
