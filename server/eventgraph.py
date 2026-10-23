"""Gazetteer-based event location and cross-lingual event signatures.

This is deliberately not a full NER model. It recognises countries, major
cities, key actors/organisations and a compact set of event topics across the
languages in config/gazetteer.json. That is enough to (a) attach a defensible
"event country/region" to most headlines and (b) build a language-independent
signature for cross-language story clustering.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
GAZETTEER_PATH = ROOT / "config" / "gazetteer.json"

_WS = re.compile(r"\s+")


def fold(text: str) -> str:
    """Accent/width-insensitive lowercase used for Latin-script matching."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return _WS.sub(" ", text).casefold()


def _is_latin(alias: str) -> bool:
    return all(ord(ch) < 128 for ch in alias)


class _Matcher:
    __slots__ = ("id", "kind", "label", "country", "region", "strong_re", "weak_re",
                 "ambig_re", "strong_sub", "weak_sub", "ambig_sub", "specific")

    def __init__(
        self,
        item_id: str,
        kind: str,
        label: str,
        country: str | None,
        region: str | None,
        strong: list[str],
        weak: list[str] | None = None,
        ambiguous: list[str] | None = None,
        specific: bool = True,
    ) -> None:
        self.id = item_id
        self.kind = kind
        self.label = label
        self.country = country
        self.region = region
        self.specific = specific
        weak = weak or []
        ambiguous = ambiguous or []

        def split(values: list[str]) -> tuple[re.Pattern | None, list[str]]:
            latin = sorted({fold(v) for v in values if _is_latin(fold(v))}, key=len, reverse=True)
            other = sorted({fold(v) for v in values if not _is_latin(fold(v))}, key=len, reverse=True)
            pattern = None
            if latin:
                pattern = re.compile(
                    r"(?<!\w)(?:" + "|".join(re.escape(v) for v in latin) + r")(?!\w)",
                    re.IGNORECASE,
                )
            return pattern, other

        self.strong_re, self.strong_sub = split(strong)
        self.weak_re, self.weak_sub = split(weak)
        self.ambig_re, self.ambig_sub = split(ambiguous)


def _count(pattern: re.Pattern | None, subs: list[str], text: str) -> int:
    total = 0
    if pattern is not None:
        total += len(pattern.findall(text))
    for sub in subs:
        if sub and sub in text:
            total += min(text.count(sub), 2)
    return min(total, 3)


def _first_pos(pattern: re.Pattern | None, subs: list[str], text: str) -> int:
    best = 10**9
    if pattern is not None:
        match = pattern.search(text)
        if match:
            best = match.start()
    for sub in subs:
        pos = text.find(sub)
        if pos != -1:
            best = min(best, pos)
    return best


class EventGraph:
    def __init__(self, path: Path | None = None) -> None:
        data = json.loads((path or GAZETTEER_PATH).read_text(encoding="utf-8"))
        self.countries: dict[str, dict] = data["countries"]
        self.country_matchers: list[_Matcher] = []
        for iso, info in self.countries.items():
            self.country_matchers.append(
                _Matcher(
                    iso, "country", info.get("label_zh", iso), iso,
                    info.get("region", "other"),
                    info.get("aliases", []),
                    info.get("weak_aliases", []),
                    info.get("ambiguous_aliases", []),
                )
            )
        self.place_matchers = [
            _Matcher(
                item["id"], "place", item.get("label_zh", item["id"]),
                item.get("country"), item.get("region", "other"),
                item.get("aliases", []),
            )
            for item in data.get("places", [])
        ]
        self.actor_matchers = [
            _Matcher(
                item["id"], item.get("kind", "actor"),
                item.get("label_zh", item["id"]), item.get("country"), None,
                item.get("aliases", []),
            )
            for item in data.get("actors", [])
        ]
        self.region_matchers = [
            _Matcher(
                item["id"], "region", item.get("label_zh", item["id"]), None,
                item["id"], item.get("aliases", []),
            )
            for item in data.get("regions", [])
        ]
        self.topic_matchers = [
            _Matcher(
                item["id"], "topic", item.get("label_zh", item["id"]), None, None,
                item.get("aliases", []), specific=bool(item.get("specific", True)),
            )
            for item in data.get("topics", [])
        ]
        self.topic_labels = {item["id"]: item.get("label_zh", item["id"]) for item in data.get("topics", [])}
        self.specific_topics = {
            item["id"] for item in data.get("topics", []) if item.get("specific", True)
        }

    def _score(
        self, matcher: _Matcher, title: str, summary: str,
        folded_title: str, folded_summary: str,
    ) -> tuple[float, int]:
        title_hits = (
            _count(matcher.strong_re, matcher.strong_sub, folded_title) * 1.0
            + _count(matcher.weak_re, matcher.weak_sub, folded_title) * 0.55
        )
        summary_hits = (
            _count(matcher.strong_re, matcher.strong_sub, folded_summary) * 1.0
            + _count(matcher.weak_re, matcher.weak_sub, folded_summary) * 0.55
        )
        # Ambiguous aliases use the original casing (e.g. "Turkey" a country,
        # "turkey" a bird). Only capitalised occurrences count.
        ambig_counts = []
        for source in (title, summary):
            ambig = 0
            if matcher.ambig_re is not None:
                for match in matcher.ambig_re.finditer(source):
                    value = match.group(0).strip()
                    if value and (value[0].isupper() or value.isupper()):
                        ambig += 1
            for sub in matcher.ambig_sub:
                if sub and sub in source.casefold():
                    ambig += 1
            ambig_counts.append(min(ambig, 2))
        score = (
            title_hits * 3.0 + summary_hits * 1.0
            + ambig_counts[0] * 3.0 * 0.8 + ambig_counts[1] * 1.0 * 0.8
        )
        pos = _first_pos(matcher.strong_re, matcher.strong_sub, folded_title)
        return score, pos

    def extract(self, title: str, summary: str = "") -> dict[str, Any]:
        title = title or ""
        summary = summary or ""
        folded_title = fold(title)
        folded_summary = fold(summary)

        country_scores: dict[str, float] = {}
        country_pos: dict[str, int] = {}
        region_scores: dict[str, float] = {}
        places: list[dict] = []
        entities: dict[str, float] = {}
        topics: list[dict] = []

        for matcher in self.country_matchers:
            score, pos = self._score(matcher, title, summary, folded_title, folded_summary)
            if score > 0:
                country_scores[matcher.id] = score
                country_pos[matcher.id] = pos
                entities[f"PLACE:{matcher.id}"] = max(entities.get(f"PLACE:{matcher.id}", 0), score)

        for matcher in self.place_matchers:
            score, pos = self._score(matcher, title, summary, folded_title, folded_summary)
            score *= 1.35  # cities are more specific than country names
            if score <= 0:
                continue
            places.append(
                {"id": matcher.id, "label": matcher.label, "country": matcher.country,
                 "region": matcher.region, "score": round(score, 1)}
            )
            entities[f"CITY:{matcher.id}"] = max(entities.get(f"CITY:{matcher.id}", 0), score)
            if matcher.country:
                country_scores[matcher.country] = country_scores.get(matcher.country, 0) + score * 0.8
                country_pos[matcher.country] = min(
                    country_pos.get(matcher.country, pos), pos
                )
                entities[f"PLACE:{matcher.country}"] = max(
                    entities.get(f"PLACE:{matcher.country}", 0), score * 0.8
                )
            elif matcher.region:
                region_scores[matcher.region] = region_scores.get(matcher.region, 0) + score

        for matcher in self.actor_matchers:
            score, pos = self._score(matcher, title, summary, folded_title, folded_summary)
            if score > 0:
                prefix = "ORG" if matcher.kind in ("org", "organisation", "organization") else "ACTOR"
                entities[f"{prefix}:{matcher.id}"] = max(entities.get(f"{prefix}:{matcher.id}", 0), score)
                if matcher.country:
                    country_scores[matcher.country] = country_scores.get(matcher.country, 0) + score * 0.7
                    country_pos[matcher.country] = min(country_pos.get(matcher.country, pos), pos)
                    entities[f"PLACE:{matcher.country}"] = max(
                        entities.get(f"PLACE:{matcher.country}", 0), score * 0.7
                    )

        for matcher in self.region_matchers:
            score, _ = self._score(matcher, title, summary, folded_title, folded_summary)
            if score > 0:
                region_scores[matcher.id] = region_scores.get(matcher.id, 0) + score

        for matcher in self.topic_matchers:
            score, _ = self._score(matcher, title, summary, folded_title, folded_summary)
            if score > 0:
                topics.append(
                    {"id": matcher.id, "label": matcher.label,
                     "specific": matcher.specific, "score": round(score, 1)}
                )

        # Choose the primary event country. A title hit is worth 3, a summary
        # hit 1; two summary mentions can qualify but a single incidental one
        # cannot. Cities add a strong bonus via the loop above.
        event_country = None
        if country_scores:
            ranked = sorted(
                country_scores.items(),
                key=lambda kv: (-kv[1], country_pos.get(kv[0], 10**9), kv[0]),
            )
            if ranked[0][1] >= 2.0:
                event_country = ranked[0][0]

        event_region = None
        if event_country:
            event_region = self.countries.get(event_country, {}).get("region", "other")
        elif region_scores:
            best_region = max(region_scores, key=region_scores.get)
            if region_scores[best_region] >= 2.0:
                event_region = best_region

        top_places = sorted(places, key=lambda p: (-p["score"], p["id"]))[:5]
        top_topics = sorted(topics, key=lambda t: (-t["score"], t["id"]))[:8]
        entity_ids = [
            key for key, _ in sorted(entities.items(), key=lambda kv: (-kv[1], kv[0]))[:24]
        ]

        if event_country and top_places:
            confidence = "high"
        elif event_country:
            confidence = "medium"
        elif event_region:
            confidence = "region"
        else:
            confidence = "none"

        return {
            "event_country": event_country,
            "event_region": event_region,
            "event_places": top_places,
            "event_entities": entity_ids,
            "event_topics": top_topics,
            "event_confidence": confidence,
            "event_countries": [
                {"code": code, "score": round(score, 1)}
                for code, score in sorted(
                    country_scores.items(), key=lambda kv: (-kv[1], country_pos.get(kv[0], 10**9))
                )[:5]
            ],
        }


_cache: EventGraph | None = None


def graph() -> EventGraph:
    global _cache
    if _cache is None:
        _cache = EventGraph()
    return _cache
