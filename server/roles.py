"""Role labels for the event homepage.

A cluster can contain a first-hand report, wire/aggregator reposts, lateral
coverage from other outlets, and government/official statements. This module
keeps that classification deterministic and easy to inspect.
"""
from __future__ import annotations

import re

ROLE_LABELS = {
    "original": "第一手",
    "repost": "转载",
    "angle": "其他角度",
    "statement": "政府/官方声明",
    "analysis": "分析",
    "opinion": "评论",
}

# Strong institutional cues (weight 2). Generic words like "statement" or
# "spokesperson" are weak cues (weight 1), and require either an institution
# or state ownership to reach the statement threshold.
STRONG_TERMS = (
    "foreign ministry", "ministry of foreign affairs", "defense ministry",
    "ministry of defense", "state department", "white house", "pentagon",
    "kremlin", "elysee", "élysée", "quai d'orsay", "auswartiges amt",
    "auswärtiges amt", "casa blanca", "maison blanche", "itamaraty",
    "cancilleria", "cancillería",
    "外交部", "国防部", "国务院", "白宫", "官方通报", "新闻办", "记者会",
    "答记者问", "总统府", "总理府", "政府声明", "克里姆林宫", "五角大楼",
    "мид", "кремль", "пресс-секретарь", "официальный представитель",
    "وزارة الخارجية", "البيت الأبيض",
)
WEAK_TERMS = (
    "statement", "press release", "press statement", "communique", "communiqué",
    "readout", "spokesperson", "spokesman", "spokeswoman", "press secretary",
    "声明", "发言人", "公告",
    "заявление", "заявил", "заява",
    "بيان", "المتحدث", "بیانیه", "سخنگو", "הצהרה", "דובר",
    "comunicado", "portavoz", "porte-parole", "erklärung", "sprecher",
    "açıklama", "sözcü",
)

def _text(member: dict) -> str:
    return f"{member.get('title') or ''} {member.get('summary') or ''}".casefold()


def statement_score(member: dict) -> int:
    """Weighted official-statement score; threshold is 2."""
    text = _text(member)
    return sum(2 for term in STRONG_TERMS if term.casefold() in text) + sum(
        1 for term in WEAK_TERMS if term.casefold() in text
    )


def is_aggregator(member: dict) -> bool:
    feed_id = str(member.get("feed_id") or "").lower()
    publisher = str(member.get("publisher") or "").lower()
    return feed_id.startswith("gnews") or "google news" in publisher


def title_key(title: str) -> str:
    return re.sub(r"[^\w㐀-鿿]+", " ", str(title or "").casefold()).strip()


def _is_hard(member: dict) -> bool:
    return (member.get("content_type") or "hard") == "hard"


def choose_primary(members: list[dict]) -> dict | None:
    """Prefer a recent direct first-hand hard-news report over a statement."""
    if not members:
        return None
    ordered = sorted(
        members,
        key=lambda member: str(member.get("published_at") or ""),
        reverse=True,
    )

    def first(predicate):
        for member in ordered:
            if predicate(member):
                return member
        return None

    candidates = [
        lambda member: _is_hard(member) and statement_score(member) < 2 and not is_aggregator(member),
        lambda member: _is_hard(member) and statement_score(member) < 2,
        lambda member: _is_hard(member),
    ]
    for predicate in candidates:
        found = first(predicate)
        if found is not None:
            return found
    return ordered[0]


def classify_roles(members: list[dict], lead: dict | None) -> dict[int, str]:
    """Return ``id(member) -> role`` for one event cluster."""
    publishers_by_title: dict[str, set[str]] = {}
    for member in members:
        key = title_key(member.get("title", ""))
        publishers_by_title.setdefault(key, set()).add(str(member.get("publisher") or ""))

    roles: dict[int, str] = {}
    for member in members:
        content_type = member.get("content_type") or "hard"
        if member is lead:
            if content_type in ("analysis", "opinion"):
                role = content_type
            elif statement_score(member) >= 2:
                role = "statement"
            else:
                role = "original"
        elif content_type in ("analysis", "opinion"):
            role = content_type
        elif statement_score(member) >= 2:
            role = "statement"
        else:
            key = title_key(member.get("title", ""))
            duplicated = len(publishers_by_title.get(key, set())) > 1
            role = "repost" if duplicated else "angle"
        roles[id(member)] = role
    return roles
