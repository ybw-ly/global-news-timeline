"""Rule-based multilingual news classifier.

The classifier is intentionally deterministic: no API keys, no model downloads,
and the same headline always gets the same label. Multilingual keyword lists
live in config/lexicon.json and can be edited without touching code.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = ("economy", "politics", "military")
_NON_LATIN = re.compile(r"[^\x00-\x7f]")

# Ambiguous single words that are weak evidence on their own. They still
# contribute, but a headline needs another signal (or a source hint) to cross
# the classification threshold.
GENERIC = {
    "economy": {
        "market", "markets", "bank", "banking", "oil", "gas", "energy",
        "price", "prices", "cost", "costs", "trade", "growth", "business",
        "company", "shares", "stock", "stocks", "sales", "consumer",
        "市场", "银行", "石油", "能源", "价格", "成本", "贸易", "增长",
        "企业", "商业", "市場", "銀行", "價格", "貿易", "增長", "企業", "商業",
    },
    "politics": {
        "party", "law", "court", "policy", "reform", "regulation",
        "border", "talks", "agreement", "summit", "coalition",
        "政党", "法律", "法院", "政策", "改革", "监管", "边境", "谈判",
        "协议", "峰会", "政黨", "監管", "邊境", "談判", "協議", "峰會",
    },
    "military": {
        "attack", "strike", "security", "forces", "weapons",
        "袭击", "打击", "安全", "部队", "武器", "襲擊", "部隊",
    },
}


class Classifier:
    def __init__(self, path: Path | None = None, data: dict | None = None) -> None:
        if data is None:
            if path is not None:
                raw = json.loads(path.read_text(encoding="utf-8"))
            else:
                import customization

                raw = customization.read_json("lexicon")
        else:
            raw = data
        self.rules: dict[str, dict[str, list[tuple[str, float, re.Pattern | None]]]] = {}
        for category in CATEGORIES:
            self.rules[category] = {}
            for language, words in raw.get(category, {}).items():
                compiled = []
                for word in words:
                    keyword = word.strip().lower()
                    if not keyword:
                        continue
                    weight = 1.6 if " " in keyword else 1.0
                    if keyword in GENERIC[category]:
                        weight *= 0.55
                    if _NON_LATIN.search(keyword):
                        pattern = None
                    else:
                        pattern = re.compile(
                            r"(?<!\w)" + re.escape(keyword) + r"(?!\w)",
                            re.IGNORECASE,
                        )
                    compiled.append((keyword, weight, pattern))
                self.rules[category][language] = compiled

    def _rules_for(self, category: str, language: str):
        rules = self.rules[category]
        if language == "zh-Hant":
            return rules.get("zh-Hant") or rules.get("zh") or rules.get("en", [])
        base = (language or "en").split("-")[0]
        return rules.get(language) or rules.get(base) or rules.get("en", [])

    def classify(
        self,
        title: str,
        summary: str = "",
        language: str = "en",
        hint: str | None = None,
    ) -> dict:
        title_l = (title or "").lower()
        summary_l = (summary or "").lower()
        scores = {category: 0.0 for category in CATEGORIES}
        title_scores = {category: 0.0 for category in CATEGORIES}
        matched: dict[str, list[str]] = {category: [] for category in CATEGORIES}

        for category in CATEGORIES:
            rules = self._rules_for(category, language)
            for keyword, weight, pattern in rules:
                if pattern is None:
                    title_hits = min(title_l.count(keyword), 2)
                    summary_hits = min(summary_l.count(keyword), 2)
                else:
                    title_hits = min(len(pattern.findall(title_l)), 2)
                    summary_hits = min(len(pattern.findall(summary_l)), 2)
                if not title_hits and not summary_hits:
                    continue
                scores[category] += title_hits * 2.2 * weight + summary_hits * 1.0 * weight
                title_scores[category] += title_hits * 2.2 * weight
                if keyword not in matched[category]:
                    matched[category].append(keyword)

        if hint in scores:
            scores[hint] += 1.8
            title_scores[hint] += 0.9

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_category, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0

        if top_score < 2.0:
            category = hint if hint in CATEGORIES else "other"
        elif second_score > 0 and top_score / max(second_score, 0.001) < 1.12:
            # Ambiguous: prefer the source's editorial cue when it is involved,
            # otherwise prefer the category with the stronger headline signal.
            if hint in CATEGORIES and scores[hint] >= top_score * 0.9:
                category = hint
            else:
                category = max(CATEGORIES, key=lambda c: (title_scores[c], scores[c]))
        else:
            category = top_category

        terms = [
            term
            for term in sorted(
                matched.get(category, []), key=lambda t: len(t), reverse=True
            )[:5]
        ]
        return {
            "category": category,
            "scores": {k: round(v, 2) for k, v in scores.items()},
            "terms": terms,
        }


def load_classifier() -> Classifier:
    return Classifier()
