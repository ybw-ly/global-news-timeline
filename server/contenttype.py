"""Classify content as hard news, analysis, or opinion.

Signals, strongest first:
- RSS <category> values and article URL sections such as /opinion/ or /analysis/
- multilingual title/summary cues
- first-person and question framing (weak signals)

The label is deliberately conservative: "hard" means no editorial/analysis
markers were detected, not that the article has been fact-checked.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from taxonomy import base_language

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = ("hard", "analysis", "opinion")
_WEAK = {"why ", "how ", "what ", "comment", "view"}


class ContentTypeClassifier:
    def __init__(self, path: Path | None = None, data: dict | None = None) -> None:
        if data is None:
            if path is not None:
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                import customization

                data = customization.read_json("content_types")
        self.rules: dict[str, dict[str, list[tuple[str, float, re.Pattern | None]]]] = {}
        for category in ("opinion", "analysis", "hard"):
            self.rules[category] = {}
            for language, words in data.get(category, {}).items():
                compiled = []
                for word in words:
                    keyword = word.strip().lower()
                    if not keyword:
                        continue
                    weight = 0.6 if keyword in _WEAK else 2.0
                    if category == "hard":
                        weight = 0.8
                    pattern = None
                    if all(ord(ch) < 128 for ch in keyword):
                        pattern = re.compile(
                            r"(?<!\w)" + re.escape(keyword.strip()) + r"(?!\w)",
                            re.IGNORECASE,
                        )
                    compiled.append((keyword, weight, pattern))
                self.rules[category][language] = compiled
        self.first_person = {}
        for language, words in data.get("first_person", {}).items():
            patterns = []
            for word in words:
                keyword = word.strip().lower()
                if keyword:
                    patterns.append(re.compile(
                        r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", re.IGNORECASE
                    ))
            self.first_person[language] = patterns
        self.url_paths = data.get("url_paths", {})

    def _rules(self, category: str, language: str):
        rules = self.rules[category]
        return (
            rules.get(language)
            or rules.get(base_language(language))
            or rules.get("en", [])
        )

    def classify(
        self,
        title: str,
        summary: str = "",
        url: str = "",
        categories: list[str] | None = None,
        language: str = "en",
        hint: str | None = None,
    ) -> dict:
        title_l = (title or "").lower()
        summary_l = (summary or "").lower()
        category_text = " ".join(categories or []).lower()
        url_l = (url or "").lower()
        terms: list[str] = []

        opinion_tag = any(
            token in category_text
            for token in ("opinion", "editorial", "op-ed", "comment", "column", "voices", "perspective")
        )
        analysis_tag = any(
            token in category_text
            for token in ("analysis", "explainer", "explained", "background")
        )
        if any(path in url_l for path in self.url_paths.get("opinion", [])):
            opinion_tag = True
        if any(path in url_l for path in self.url_paths.get("analysis", [])):
            analysis_tag = True
        if hint == "opinion":
            opinion_tag = True
            terms.append("source:opinion")
        elif hint == "analysis":
            analysis_tag = True
            terms.append("source:analysis")
        if opinion_tag:
            terms.append("section:opinion")
        if analysis_tag:
            terms.append("section:analysis")

        scores = {"opinion": 0.0, "analysis": 0.0, "hard": 0.0}
        for category in ("opinion", "analysis", "hard"):
            for keyword, weight, pattern in self._rules(category, language):
                if pattern is not None:
                    title_hits = min(len(pattern.findall(title_l)), 2)
                    summary_hits = min(len(pattern.findall(summary_l)), 2)
                else:
                    title_hits = min(title_l.count(keyword), 2)
                    summary_hits = min(summary_l.count(keyword), 2)
                if not title_hits and not summary_hits:
                    continue
                scores[category] += title_hits * weight + summary_hits * weight * 0.35
                if keyword.strip() not in terms:
                    terms.append(keyword.strip())

        fp = self.first_person.get(language) or self.first_person.get(base_language(language), [])
        fp_hits = sum(1 for pattern in fp if pattern.search(title_l))
        scores["opinion"] += min(fp_hits, 2) * 0.5
        if fp_hits:
            terms.append("first-person")

        if "?" in title and scores["analysis"] > 0:
            scores["analysis"] += 0.3

        if hint in ("hard", "analysis", "opinion"):
            # Feed-level override: prediction-market data is intentionally
            # shown as a hard data card, not misread as commentary.
            content_type = hint
        elif opinion_tag or scores["opinion"] >= 2.0:
            content_type = "opinion"
        elif analysis_tag or scores["analysis"] >= 1.8:
            content_type = "analysis"
        else:
            content_type = "hard"

        # Keep the most informative terms for the drawer/CSV.
        ordered = []
        for term in terms:
            if term not in ordered:
                ordered.append(term)
        return {
            "content_type": content_type,
            "content_type_score": {k: round(v, 2) for k, v in scores.items()},
            "content_type_terms": ordered[:6],
        }


_cache: ContentTypeClassifier | None = None


def classifier() -> ContentTypeClassifier:
    global _cache
    if _cache is None:
        _cache = ContentTypeClassifier()
    return _cache


def reset() -> None:
    global _cache
    _cache = None
