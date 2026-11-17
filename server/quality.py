"""Drop service content, lifestyle clickbait, and PR notices at ingestion.

The content-type classifier labels nearly everything "hard" because it only
looks for editorial/analysis markers. This module is a separate, explicit
quality gate driven by ``config/quality.json``:

* rules are evaluated top-down and the first match wins
* ``feeds`` / ``languages`` narrow a rule to the sources where the pattern is
  actually spam (a health keyword is legitimate on STAT News, not on an
  Indonesian business feed)
* ``unless`` rescues real news that happens to contain a soft keyword

Filtered rows are never inserted. ``scripts/apply_quality_filter.py`` applies
the same rules to rows that were ingested before this gate existed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from taxonomy import base_language

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "quality.json"
FIELDS = ("title", "summary", "url")


class QualityFilter:
    def __init__(self, path: Path | None = None) -> None:
        data = json.loads((path or CONFIG_PATH).read_text(encoding="utf-8"))
        self.enabled = bool(data.get("enabled", True))
        self.rules: list[dict[str, Any]] = []
        for index, rule in enumerate(data.get("rules", [])):
            patterns = {}
            for field in FIELDS:
                value = rule.get(field)
                if value:
                    patterns[field] = re.compile(value, re.IGNORECASE | re.UNICODE)
            if not patterns:
                continue
            unless = rule.get("unless")
            self.rules.append(
                {
                    "id": str(rule.get("id") or f"rule-{index}"),
                    "feeds": {str(item) for item in rule.get("feeds", [])},
                    "languages": {str(item).casefold() for item in rule.get("languages", [])},
                    "patterns": patterns,
                    "unless": re.compile(unless, re.IGNORECASE | re.UNICODE) if unless else None,
                }
            )

    def match(
        self,
        title: str,
        summary: str = "",
        url: str = "",
        language: str = "",
        feed_id: str = "",
    ) -> str | None:
        """Return the matching rule id, or None when the item is acceptable."""
        if not self.enabled:
            return None
        values = {"title": title or "", "summary": summary or "", "url": url or ""}
        lang = (language or "").casefold()
        base = base_language(language or "").casefold()
        for rule in self.rules:
            feeds = rule["feeds"]
            if feeds and feed_id not in feeds:
                continue
            languages = rule["languages"]
            if languages and lang not in languages and base not in languages:
                continue
            matched_fields = [
                field for field, pattern in rule["patterns"].items() if pattern.search(values[field])
            ]
            if not matched_fields:
                continue
            unless = rule["unless"]
            # Rescue terms are checked against the field that triggered the
            # rule (plus the title), never the URL. A URL slug like
            # "toyokeizai.net" contains "ai", and a clickbait summary may
            # mention "debt" while the headline is still a wealth listicle.
            rescue_fields = set(matched_fields) | {"title"}
            if unless and any(
                unless.search(values[field]) for field in rescue_fields if values[field]
            ):
                continue
            return rule["id"]
        return None


_cache: QualityFilter | None = None


def quality_filter() -> QualityFilter:
    global _cache
    if _cache is None:
        _cache = QualityFilter()
    return _cache
