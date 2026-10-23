"""Text cleaning, URL canonicalization and lightweight story clustering."""
from __future__ import annotations

import hashlib
import html
import json
import re
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from roles import ROLE_LABELS, choose_primary, classify_roles

_WS = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")
_TRACKING = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "at_medium", "at_campaign", "at_custom1",
    "at_custom2", "at_custom3", "at_custom4", "fbclid", "gclid", "yclid",
    "mc_cid", "mc_eid", "cmpid", "ocid", "ref", "referrer", "source",
    "spm", "from", "share_token", "smid", "partner",
}
_CJK = re.compile(r"[㐀-鿿぀-ヿ가-힯]")
_TOKEN = re.compile(r"[a-zA-ZÀ-ÿА-яА-Я0-9㐀-鿿぀-ヿ가-힯]+")

SPECIFIC_TOPICS = {
    "CEASEFIRE", "ELECTION", "PROTEST", "SANCTIONS", "TARIFF_TRADE",
    "RATES_INFLATION", "OIL_ENERGY", "NUCLEAR", "AIRSTRIKE_MISSILE",
    "HOSTAGE", "EARTHQUAKE", "FLOOD_TYPHOON", "SUMMIT_DIPLOMACY", "AI_CHIPS",
}
# Topics specific enough to merge two country-level stories. Elections and
# protests are too broad: a shared country + "election" is not one event.
STRICT_TOPICS = {
    "CEASEFIRE", "SANCTIONS", "TARIFF_TRADE", "OIL_ENERGY", "NUCLEAR",
    "AIRSTRIKE_MISSILE", "HOSTAGE", "EARTHQUAKE", "FLOOD_TYPHOON", "AI_CHIPS",
}

_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "at", "by", "from", "as", "is", "are", "was", "were", "be", "been",
    "that", "this", "these", "those", "it", "its", "his", "her", "their",
    "after", "before", "over", "under", "about", "into", "than", "says",
    "said", "new", "will", "would", "could", "has", "have", "had",
    "le", "la", "les", "des", "du", "et", "en", "pour", "avec", "sur",
    "el", "los", "las", "de", "que", "por", "para", "con", "una", "del",
    "der", "die", "das", "und", "von", "mit", "für", "auf", "ist",
    "o", "os", "as", "que", "em", "com", "não", "um", "uma", "do", "da",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def strip_html(value: str | None, limit: int | None = None) -> str:
    if not value:
        return ""
    if "<" in value and ">" in value:
        parser = _TextExtractor()
        try:
            parser.feed(value)
            text = " ".join(parser.parts)
        except Exception:
            text = _TAG.sub(" ", value)
    else:
        text = value
    text = html.unescape(text)
    text = _WS.sub(" ", text).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def clean_title(title: str | None, publisher: str | None = None) -> str:
    text = strip_html(title)
    if publisher:
        suffix = f" - {publisher}"
        if text.endswith(suffix):
            text = text[: -len(suffix)].rstrip()
        suffix = f" | {publisher}"
        if text.endswith(suffix):
            text = text[: -len(suffix)].rstrip()
    return text.strip(" -–—|")


def normalize_title(title: str) -> str:
    text = html.unescape(title or "").lower()
    text = re.sub(r"[^\w㐀-鿿぀-ヿ가-힯]+", " ", text)
    return _WS.sub(" ", text).strip()


def fingerprint(title: str) -> str:
    return hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()


def article_id(url: str, title: str = "") -> str:
    key = canonical_url(url) or normalize_title(title)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def canonical_url(url: str | None) -> str:
    if not url:
        return ""
    url = html.unescape(url.strip())
    try:
        parts = urlsplit(url)
    except Exception:
        return url
    if parts.scheme not in ("http", "https"):
        return url
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING
    ]
    path = parts.path or "/"
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), "")
    )


def ensure_http(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith(("http://", "https://")):
        return None
    return url


def tokenize(title: str, language: str = "en") -> set[str]:
    text = normalize_title(title)
    if not text:
        return set()
    if language in ("zh", "zh-Hant", "ja", "ko"):
        chars = _CJK.findall(text)
        # Character bigrams work well for unsegmented CJK headlines.
        cjk_text = "".join(chars)
        grams = {cjk_text[i : i + 2] for i in range(len(cjk_text) - 1)}
        words = {w for w in _TOKEN.findall(text) if len(w) >= 2 and w not in _STOP}
        return grams | words
    words = {w for w in _TOKEN.findall(text) if len(w) >= 3 and w not in _STOP}
    return words


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def _as_list(value) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    return value if isinstance(value, list) else []


def _topic_ids(value) -> set[str]:
    ids = set()
    for item in _as_list(value):
        topic_id = item.get("id") if isinstance(item, dict) else item
        if topic_id:
            ids.add(str(topic_id))
    return ids


def _topic_labels(value) -> list[str]:
    labels = []
    for item in _as_list(value):
        label = (item.get("label") or item.get("id")) if isinstance(item, dict) else item
        if label and str(label) not in labels:
            labels.append(str(label))
    return labels


def _timestamp(value) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


CORROBORATION_LABELS = {
    "strong": "强交叉印证",
    "multi": "多源印证",
    "single": "单一信源",
    "opinion": "评论/分析为主",
}


def _corroboration(members: list[dict]) -> dict:
    publishers = {str(m.get("publisher") or "").strip().casefold() for m in members}
    publishers.discard("")
    countries = {m.get("country") for m in members if m.get("country")}
    languages = {m.get("language") for m in members if m.get("language")}
    types = Counter((m.get("content_type") or "hard") for m in members)
    hard = types.get("hard", 0)
    analysis = types.get("analysis", 0)
    opinion = types.get("opinion", 0)
    state_publishers = {
        str(m.get("publisher") or "").strip().casefold()
        for m in members
        if m.get("ownership") in ("state", "state_funded")
    }
    state_publishers.discard("")
    public_publishers = {
        str(m.get("publisher") or "").strip().casefold()
        for m in members
        if m.get("ownership") == "public"
    }
    public_publishers.discard("")
    state_media = len(state_publishers)
    public_service = len(public_publishers)
    times = [m.get("published_at") for m in members if m.get("published_at")]

    if hard == 0 and (analysis + opinion) > 0:
        level = "opinion"
    elif len(publishers) >= 3 and len(countries) >= 2 and len(languages) >= 2:
        level = "strong"
    elif len(publishers) >= 5 and (len(countries) >= 2 or len(languages) >= 2):
        level = "strong"
    elif len(publishers) >= 2:
        level = "multi"
    else:
        level = "single"

    notes = []
    if level == "single":
        notes.append("仅 1 家媒体，尚无独立交叉印证")
    if level == "opinion":
        notes.append("以评论/分析为主，不能作为事实确认")
    if publishers and state_media == len(publishers):
        notes.append("信源均为国有/国营媒体")
    if len(countries) >= 2 and len(languages) >= 2:
        notes.append("跨国家、跨语种报道")
    if hard > 0 and (analysis + opinion) > 0:
        notes.append("包含评论/分析内容")

    return {
        "level": level,
        "label": CORROBORATION_LABELS[level],
        "publishers": len(publishers),
        "countries": len(countries),
        "languages": len(languages),
        "hard": hard,
        "analysis": analysis,
        "opinion": opinion,
        "coverage": len(members),
        "state_media": state_media,
        "public_service": public_service,
        "first_seen": min(times) if times else None,
        "last_seen": max(times) if times else None,
        "notes": notes,
    }


def cluster_articles(articles: list[dict]) -> list[dict]:
    """Cluster stories in two stages.

    1. Same-language title similarity (character bigrams for CJK, words for
       Latin/other scripts).
    2. Cross-language merge using canonical event signatures: a shared city,
       two shared places, or a shared actor plus a specific event topic.

    Stage two is deliberately conservative. Broad topics such as "war" never
    merge on their own. Cross-language clusters are capped at 24 members.
    """
    for article in articles:
        article["coverage"] = 1
        article["related"] = []
        article["coverage_languages"] = 1
        article["cross_language"] = False
        article["cluster_topics"] = []

    clusters: list[dict] = []
    for article in articles:
        tokens = tokenize(article.get("title", ""), article.get("language", "en"))
        lang = article.get("language", "en")
        best = None
        best_score = 0.0
        for cluster in clusters[-180:]:
            if cluster["language"] != lang:
                continue
            score = jaccard(tokens, cluster["tokens"])
            if score > best_score:
                best_score = score
                best = cluster
        if best is not None and best_score >= 0.52 and len(tokens & best["tokens"]) >= 2:
            best["members"].append(article)
        else:
            clusters.append({"language": lang, "tokens": tokens, "members": [article]})

    n = len(clusters)
    if n:
        signatures = []
        for cluster in clusters:
            entities: set[str] = set()
            topics: set[str] = set()
            newest = 0.0
            for member in cluster["members"]:
                for entity in _as_list(member.get("event_entities")):
                    if isinstance(entity, str):
                        entities.add(entity)
                topics.update(_topic_ids(member.get("event_topics")))
                newest = max(newest, _timestamp(member.get("published_at")))
            signatures.append({"entities": entities, "topics": topics, "newest": newest})

        parent = list(range(n))
        sizes = [len(c["members"]) for c in clusters]

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra == rb:
                return
            if sizes[ra] < sizes[rb]:
                ra, rb = rb, ra
            parent[rb] = ra
            sizes[ra] += sizes[rb]

        for i in range(n):
            for j in range(i + 1, n):
                if clusters[i]["language"] == clusters[j]["language"]:
                    continue
                if abs(signatures[i]["newest"] - signatures[j]["newest"]) > 36 * 3600:
                    continue
                if sizes[find(i)] + sizes[find(j)] > 24:
                    continue
                shared = signatures[i]["entities"] & signatures[j]["entities"]
                topics = signatures[i]["topics"] & signatures[j]["topics"] & SPECIFIC_TOPICS
                if not topics:
                    continue
                places = {e for e in shared if e.startswith(("PLACE:", "CITY:"))}
                cities = {e for e in shared if e.startswith("CITY:")}
                actors = {e for e in shared if e.startswith(("ACTOR:", "ORG:"))}
                strict = topics & STRICT_TOPICS
                allowed = (
                    bool(cities)
                    or (len(places) >= 2 and bool(strict))
                    or (bool(places) and bool(actors) and bool(strict))
                    or len(actors) >= 2
                )
                if not allowed:
                    continue
                union(i, j)

        groups: dict[int, list[int]] = {}
        for index in range(n):
            groups.setdefault(find(index), []).append(index)

        for indices in groups.values():
            members: list[dict] = []
            for index in indices:
                members.extend(clusters[index]["members"])
            members.sort(key=lambda m: _timestamp(m.get("published_at")), reverse=True)
            lead = choose_primary(members) or members[0]
            role_map = classify_roles(members, lead)
            for member in members:
                role = role_map.get(id(member), "angle")
                member["role"] = role
                member["role_label"] = ROLE_LABELS.get(role, role)
            others = [member for member in members if member is not lead]
            languages = {m.get("language", "en") for m in members}
            topic_labels: list[str] = []
            for member in members:
                for label in _topic_labels(member.get("event_topics")):
                    if label not in topic_labels:
                        topic_labels.append(label)
            role_counts: dict[str, int] = {}
            for role in role_map.values():
                role_counts[role] = role_counts.get(role, 0) + 1
            lead["coverage"] = len(members)
            lead["coverage_groups"] = role_counts
            lead["corroboration"] = _corroboration(members)
            lead["member_ids"] = [member.get("id") for member in others]
            lead["coverage_languages"] = len(languages)
            lead["cross_language"] = len(languages) > 1
            lead["cluster_topics"] = topic_labels[:6]
            lead["related"] = [
                {
                    "id": member.get("id"),
                    "title": member.get("title"),
                    "url": member.get("url"),
                    "publisher": member.get("publisher"),
                    "country": member.get("country"),
                    "country_label": member.get("country_label"),
                    "language": member.get("language"),
                    "language_label": member.get("language_label"),
                    "content_type": member.get("content_type", "hard"),
                    "role": member.get("role", "angle"),
                    "role_label": member.get("role_label", "其他角度"),
                    "published_at": member.get("published_at"),
                    "ownership": member.get("ownership"),
                    "ownership_label": member.get("ownership_label"),
                    "event_country": member.get("event_country"),
                    "event_country_label": member.get("event_country_label"),
                    "event_region": member.get("event_region"),
                    "event_region_label": member.get("event_region_label"),
                }
                for member in others[:24]
            ]
    return articles


def short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def diversify(items: list[dict], cooldown: int = 4) -> list[dict]:
    """Interleave publishers so a single feed's burst cannot flood the top.

    At each step take the newest item whose publisher has not appeared in the
    previous `cooldown` positions. If every remaining item is blocked, fall
    back to the newest one. Recency remains the primary signal; this only
    prevents a single outlet from owning consecutive slots.
    """
    remaining = list(items)
    result: list[dict] = []
    recent: list[str] = []
    while remaining:
        pick = 0
        for index, item in enumerate(remaining):
            if item.get("publisher") in recent[-cooldown:]:
                continue
            pick = index
            break
        item = remaining.pop(pick)
        result.append(item)
        recent.append(item.get("publisher"))
    return result
