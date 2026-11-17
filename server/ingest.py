"""RSS/Atom ingestion pipeline with conditional GET and polite scheduling."""
from __future__ import annotations

import concurrent.futures
import gzip
import hashlib
import html
import json
import logging
import os
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
from urllib.parse import urlsplit

from classifier import Classifier
from contenttype import classifier as content_classifier
from eventgraph import graph as event_graph
from quality import quality_filter
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


def _detect_proxy() -> str | None:
    """Env vars first, then the Windows system proxy (registry)."""
    for name in (
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        value = os.environ.get(name)
        if value:
            return value
    if os.name != "nt":
        return None
    try:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
            server = winreg.QueryValueEx(key, "ProxyServer")[0]
        if not enabled or not server:
            return None
        if "=" in server:
            parts = dict(part.split("=", 1) for part in server.split(";") if "=" in part)
            server = parts.get("https") or parts.get("http") or ""
        if not server:
            return None
        return server if "://" in server else "http://" + server
    except Exception:
        return None


_PROXY = _detect_proxy()
_PROXY_OPENER = (
    urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": _PROXY, "https": _PROXY})
    )
    if _PROXY
    else urllib.request.build_opener()
)
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
# 这些域名经当前代理出口时会被 TLS 重置，直连反而正常
_DIRECT_SUFFIXES = (".gov", ".mil")


def _open(request: urllib.request.Request, timeout: int):
    host = (urlsplit(request.full_url).hostname or "").lower()
    if host.endswith(_DIRECT_SUFFIXES):
        return _DIRECT_OPENER.open(request, timeout=timeout)
    try:
        return _PROXY_OPENER.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code not in (403, 407, 451):
            raise
        # 部分站点会拒绝代理出口 IP，但直连正常
        return _DIRECT_OPENER.open(request, timeout=timeout)
    except (urllib.error.URLError, OSError):
        # 代理节点偶发 TLS/连接失败，回退直连一次
        return _DIRECT_OPENER.open(request, timeout=timeout)


def load_config() -> dict:
    import customization

    return customization.read_json("feeds")


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


def _polymarket_time(value: str | None) -> str:
    if not value:
        return utcnow()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return utcnow()


def _polymarket_list(value) -> list:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


_POLYMARKET_EXCLUDED_TAGS = {
    "sports", "games", "soccer", "football", "nba", "nfl", "mlb", "nhl",
    "ufc", "boxing", "tennis", "golf", "formula-1", "basketball",
    "baseball", "hockey", "esports", "awards", "entertainment", "music",
    "movies", "tv", "celebrities", "pop-culture",
}


def _polymarket_event_item(event: dict, feed: dict) -> dict | None:
    if not isinstance(event, dict):
        return None
    tags = {
        str(tag.get("slug") or "").casefold()
        for tag in (event.get("tags") or [])
        if isinstance(tag, dict)
    }
    if tags & _POLYMARKET_EXCLUDED_TAGS:
        return None
    title = str(event.get("title") or "").strip()
    slug = str(event.get("slug") or "").strip()
    if not title or not slug:
        return None
    outcomes: list[tuple[str, float]] = []
    for market in event.get("markets") or []:
        if not isinstance(market, dict):
            continue
        if market.get("closed") or market.get("archived") or market.get("active") is False:
            continue
        label = str(market.get("groupItemTitle") or market.get("question") or "").strip()
        prices = _polymarket_list(market.get("outcomePrices"))
        try:
            price = float(prices[0]) if prices else 0.0
        except Exception:
            continue
        if not label or price <= 0.001 or price >= 0.999:
            continue
        outcomes.append((label, price))
    if not outcomes:
        return None
    outcomes.sort(key=lambda pair: pair[1], reverse=True)
    shown = outcomes[:4]
    odds = " / ".join(f"{name} {value * 100:.1f}%" for name, value in shown)
    if len(outcomes) > len(shown):
        odds += f" 等 {len(outcomes)} 个选项"
    parts = [f"预测市场：{odds}"]
    volume_value = 0.0
    try:
        volume_value = float(event.get("volume24hr") or event.get("volume") or 0)
        if volume_value > 0:
            parts.append(f"24h 成交额 ${volume_value:,.0f}")
    except Exception:
        pass
    try:
        liquidity = float(event.get("liquidity") or event.get("liquidityClob") or 0)
        if liquidity > 0:
            parts.append(f"流动性 ${liquidity:,.0f}")
    except Exception:
        pass
    end_date = str(event.get("endDate") or event.get("endDateIso") or "")[:10]
    if end_date:
        parts.append(f"截止 {end_date}")
    description = re.sub(r"\s+", " ", str(event.get("description") or "")).strip()
    if description:
        parts.append(description[:180])
    return {
        "title": title[:300],
        "url": f"https://polymarket.com/event/{slug}",
        "summary": " · ".join(parts),
        "published_at": _polymarket_time(event.get("updatedAt") or event.get("createdAt")),
        "publisher": feed.get("publisher") or "Polymarket",
        "publisher_url": feed.get("homepage") or "https://polymarket.com/",
        "image_url": event.get("image") or event.get("icon"),
        "categories": ["prediction-market"],
        "snapshot_update": True,
    }


def parse_polymarket_markets(data, feed: dict) -> list[dict]:
    """Convert Gamma API markets into the app's raw article shape."""
    markets = data if isinstance(data, list) else (data.get("markets") if isinstance(data, dict) else [])
    if not isinstance(markets, list):
        return []
    rows: list[tuple[float, dict]] = []
    for market in markets:
        if not isinstance(market, dict):
            continue
        if market.get("markets") and market.get("title"):
            event_item = _polymarket_event_item(market, feed)
            if event_item:
                try:
                    volume_value = float(market.get("volume24hr") or market.get("volume") or 0)
                except Exception:
                    volume_value = 0.0
                rows.append((volume_value, event_item))
            continue
        if market.get("closed") or market.get("archived") or market.get("active") is False:
            continue
        question = str(market.get("question") or "").strip()
        slug = str(market.get("slug") or "").strip()
        if not question or not slug:
            continue
        outcomes = [str(value) for value in _polymarket_list(market.get("outcomes"))]
        prices = _polymarket_list(market.get("outcomePrices"))
        pairs: list[tuple[str, float]] = []
        for outcome, price in zip(outcomes, prices):
            try:
                pairs.append((outcome, float(price)))
            except Exception:
                continue
        pairs.sort(key=lambda pair: pair[1], reverse=True)
        shown = pairs[:4]
        odds = " / ".join(f"{name} {value * 100:.1f}%" for name, value in shown)
        if len(pairs) > len(shown):
            odds += f" 等 {len(pairs)} 个选项"
        parts = [f"预测市场：{odds}" if odds else "预测市场"]
        volume = market.get("volume24hr") or market.get("volumeNum") or market.get("volume")
        liquidity = market.get("liquidityNum") or market.get("liquidity")
        end_date = str(market.get("endDate") or market.get("endDateIso") or "")[:10]
        volume_value = 0.0
        try:
            volume_value = float(volume or 0)
            if volume_value > 0:
                parts.append(f"24h 成交额 ${volume_value:,.0f}")
        except Exception:
            pass
        try:
            if float(liquidity or 0) > 0:
                parts.append(f"流动性 ${float(liquidity):,.0f}")
        except Exception:
            pass
        if end_date:
            parts.append(f"截止 {end_date}")
        description = re.sub(r"\s+", " ", str(market.get("description") or "")).strip()
        if description:
            parts.append(description[:220])
        rows.append((volume_value, {
            "title": question[:300],
            "url": f"https://polymarket.com/event/{slug}",
            "summary": " · ".join(parts),
            "published_at": _polymarket_time(market.get("updatedAt") or market.get("createdAt")),
            "publisher": feed.get("publisher") or "Polymarket",
            "publisher_url": feed.get("homepage") or "https://polymarket.com/",
            "image_url": market.get("image") or market.get("icon"),
            "categories": ["prediction-market"],
            "snapshot_update": True,
        }))
    rows.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in rows[: int(feed.get("max_items", 12))]]


def _fetch_polymarket(feed: dict, timeout: int, user_agent: str) -> dict:
    started = time.time()
    try:
        request = urllib.request.Request(
            feed["url"],
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Accept-Language": "en,*;q=0.5",
            },
        )
        with _open(request, timeout) as response:
            # Gamma API 的 events 响应含嵌套 markets/tokens，随热度增长会超过 16 MiB；
            # 截断读取会在字符串中间断开，json 直接报 Unterminated string。
            data = json.loads(response.read(64 * 1024 * 1024).decode("utf-8"))
        items = parse_polymarket_markets(data, feed)
        return {
            "feed": feed,
            "status": "ok" if items else "empty",
            "items": items,
            "etag": None,
            "last_modified": None,
            "error": None,
            "seconds": round(time.time() - started, 1),
        }
    except Exception as exc:
        return {
            "feed": feed,
            "status": "error",
            "items": [],
            "etag": None,
            "last_modified": None,
            "error": f"Polymarket: {str(exc)[:160]}",
            "seconds": round(time.time() - started, 1),
        }


def _jin10_time(value: str | None) -> str:
    if not value:
        return utcnow()
    try:
        parsed = datetime.strptime(str(value).strip(), "%Y-%m-%d %H:%M:%S")
        return parsed.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(
            timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return utcnow()


def parse_jin10_flash(data, feed: dict) -> list[dict]:
    """Convert the jin10 flash-list JSON into the app's raw article shape."""
    entries = data.get("data") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return []
    items: list[dict] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        flash_id = str(entry.get("id") or "").strip()
        if not flash_id or flash_id in seen:
            continue
        payload = entry.get("data") if isinstance(entry.get("data"), dict) else {}
        title = str(payload.get("title") or "").strip()
        content = str(payload.get("content") or "").strip()
        content = html.unescape(re.sub(r"<[^>]+>", " ", content))
        content = re.sub(r"\s+", " ", content).strip()
        headline = title or content
        if not headline:
            continue
        seen.add(flash_id)
        items.append(
            {
                "title": headline[:300],
                "url": f"https://flash.jin10.com/detail/{flash_id}",
                "summary": content[:400] if title else "",
                "published_at": _jin10_time(entry.get("time")),
                "publisher": feed.get("publisher") or "金十数据",
                "publisher_url": feed.get("homepage") or "https://www.jin10.com/",
                "image_url": payload.get("pic") or None,
                "categories": ["flash"],
            }
        )
    items.sort(key=lambda item: item["published_at"], reverse=True)
    return items[: int(feed.get("max_items", 15))]


def _fetch_jin10(feed: dict, timeout: int, user_agent: str) -> dict:
    started = time.time()
    try:
        request = urllib.request.Request(
            feed["url"],
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
                "x-app-id": "bVBF4FyRTn5NJF5n",
                "x-version": "1.0.0",
                "Referer": "https://www.jin10.com/",
            },
        )
        with _open(request, timeout) as response:
            data = json.loads(response.read(8 * 1024 * 1024).decode("utf-8"))
        if isinstance(data, dict) and data.get("status") not in (None, 200):
            raise RuntimeError(
                f"status={data.get('status')} {data.get('message') or ''}".strip()
            )
        items = parse_jin10_flash(data, feed)
        return {
            "feed": feed,
            "status": "ok" if items else "empty",
            "items": items,
            "etag": None,
            "last_modified": None,
            "error": None,
            "seconds": round(time.time() - started, 1),
        }
    except Exception as exc:
        return {
            "feed": feed,
            "status": "error",
            "items": [],
            "etag": None,
            "last_modified": None,
            "error": f"jin10: {str(exc)[:160]}",
            "seconds": round(time.time() - started, 1),
        }


def _fetch(
    feed: dict, state: dict | None, timeout: int, user_agent: str, force: bool
) -> dict:
    if feed.get("connector") == "polymarket":
        return _fetch_polymarket(feed, timeout, user_agent)
    if feed.get("connector") == "jin10":
        return _fetch_jin10(feed, timeout, user_agent)
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
            with _open(request, timeout) as response:
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
        "snapshot_update": bool(raw.get("snapshot_update")),
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
        qf = quality_filter()
        total_new = 0
        total_items = 0
        total_filtered = 0
        ok = errors = 0
        for result in results:
            feed = result["feed"]
            items = result["items"]
            kept = []
            for item in items:
                reason = qf.match(
                    item["title"],
                    item.get("summary", ""),
                    item["url"],
                    feed.get("language", ""),
                    feed["id"],
                )
                if reason:
                    total_filtered += 1
                    continue
                kept.append(item)
            parsed = [
                article
                for article in (build_article(item, feed, classifier, eg, ctype) for item in kept)
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
                "%-22s %-12s items=%-3s kept=%-3s filtered=%-3s new=%-3s %.1fs %s",
                feed["id"], result["status"], len(items), len(parsed),
                len(items) - len(kept), new, result["seconds"],
                result["error"] or "",
            )

        duration = round(time.time() - started, 1)
        if results:
            meta_set(conn, "last_ingest_at", utcnow())
            meta_set(conn, "last_new_count", str(total_new))
            meta_set(conn, "last_item_count", str(total_items))
            meta_set(conn, "last_filtered_count", str(total_filtered))
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
            "filtered": total_filtered,
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
