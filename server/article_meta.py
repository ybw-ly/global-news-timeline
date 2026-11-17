"""Fetch a short description from an article page for share cards.

Only the page's ``<meta>`` description / OpenGraph description (or a JSON-LD
description) is extracted.  Full article text is never stored.  Private,
loopback and link-local targets are blocked to keep the endpoint from becoming
an SSRF helper.
"""
from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import threading
import time
import urllib.parse
import urllib.request

CACHE_TTL = 3600
MAX_BYTES = 512 * 1024
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 GlobalNewsTimeline/1.0"
)

_CACHE: dict[str, tuple[float, dict]] = {}
_LOCK = threading.Lock()
_META_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(
    r"""([a-zA-Z:_-]+)\s*=\s*"([^"]*)"|([a-zA-Z:_-]+)\s*=\s*'([^']*)'""",
    re.IGNORECASE,
)
_JSONLD_RE = re.compile(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _attrs(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _ATTR_RE.finditer(tag):
        key = (match.group(1) or match.group(3) or "").lower()
        value = match.group(2) if match.group(1) else match.group(4)
        if key:
            attrs[key] = value or ""
    return attrs


def _clean(text: str) -> str:
    value = html.unescape(text or "")
    value = _TAG_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:600]


def _public_host(host: str) -> bool:
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def _extract(page: str) -> str:
    candidates: list[str] = []
    for tag in _META_RE.findall(page):
        attrs = _attrs(tag)
        key = (attrs.get("name") or attrs.get("property") or "").lower()
        if key in ("description", "og:description", "twitter:description"):
            content = _clean(attrs.get("content", ""))
            if content:
                candidates.append(content)
    if not candidates:
        for match in _JSONLD_RE.finditer(page):
            try:
                value = json.loads(f'"{match.group(1)}"')
            except (ValueError, json.JSONDecodeError):
                value = match.group(1)
            value = _clean(value)
            if value:
                candidates.append(value)
    unique = list(dict.fromkeys(candidates))
    return max(unique, key=len) if unique else ""


def fetch_description(url: str) -> dict:
    url = (url or "").strip()
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return {"ok": False, "url": url, "error": "Invalid URL"}
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {"ok": False, "url": url, "error": "Only http(s) URLs are supported"}
    if not _public_host(parsed.hostname):
        return {"ok": False, "url": url, "error": "URL host is not public"}

    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(url)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]

    import ingest

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en,*;q=0.5",
        },
    )
    try:
        with ingest._open(request, 9) as response:
            final_url = response.geturl()
            final_host = urllib.parse.urlsplit(final_url).hostname or ""
            if not _public_host(final_host):
                result = {
                    "ok": False,
                    "url": url,
                    "error": "Redirected to a non-public host",
                }
            else:
                raw = response.read(MAX_BYTES)
                charset = response.headers.get_content_charset() or "utf-8"
                try:
                    page = raw.decode(charset, "replace")
                except LookupError:
                    page = raw.decode("utf-8", "replace")
                description = _extract(page)
                result = {
                    "ok": bool(description),
                    "url": url,
                    "final_url": final_url,
                    "description": description,
                    "error": "" if description else "No meta description found",
                }
    except Exception as exc:  # noqa: BLE001 - report a short network error
        result = {"ok": False, "url": url, "error": str(exc)[:160]}

    with _LOCK:
        _CACHE[url] = (now, result)
    return result
