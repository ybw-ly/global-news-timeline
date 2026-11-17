"""Cross-language search expansion.

The user's query is translated into every supported news language with the
same provider chain used by the article translator. The original query and all
successful translations are then searched together.

Design constraints:
- Translation is cached in the existing ``translations`` table.
- Queries are translated in parallel with a short deadline. A slow/limited
  provider therefore returns a partial expansion instead of blocking search
  indefinitely; successful results are cached for the next query.
- No translated text is trusted as HTML; it is only used in parameterized SQL
  LIKE patterns.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import threading
import time
from pathlib import Path

import customization
from db import connect
from taxonomy import LANGUAGES, detect_language
from translate import PROVIDER_LABELS, cached_translation, translate

ROOT = Path(__file__).resolve().parent.parent
NO_SPACE_LANGUAGES = {"zh", "zh-Hant", "ja", "th"}
CJK_LANGUAGES = {"zh", "zh-Hant", "ja"}
MAX_VARIANTS = 32


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "off", "no")


SEARCH_TRANSLATE = _env_bool("SEARCH_TRANSLATE", True)
try:
    SEARCH_TRANSLATE_WORKERS = max(1, min(12, int(os.environ.get("SEARCH_TRANSLATE_WORKERS", "4"))))
except ValueError:
    SEARCH_TRANSLATE_WORKERS = 4
try:
    SEARCH_TRANSLATE_DEADLINE = max(1.0, min(20.0, float(os.environ.get("SEARCH_TRANSLATE_DEADLINE", "4.5"))))
except ValueError:
    SEARCH_TRANSLATE_DEADLINE = 4.5
try:
    SEARCH_TRANSLATE_CACHED_DEADLINE = max(0.5, min(10.0, float(os.environ.get("SEARCH_TRANSLATE_CACHED_DEADLINE", "1.5"))))
except ValueError:
    SEARCH_TRANSLATE_CACHED_DEADLINE = 1.5
try:
    SEARCH_TRANSLATE_SYNC_LIMIT = max(1, min(20, int(os.environ.get("SEARCH_TRANSLATE_SYNC_LIMIT", "8"))))
except ValueError:
    SEARCH_TRANSLATE_SYNC_LIMIT = 8
try:
    SEARCH_TRANSLATE_BACKGROUND_WORKERS = max(1, min(6, int(os.environ.get("SEARCH_TRANSLATE_BACKGROUND_WORKERS", "3"))))
except ValueError:
    SEARCH_TRANSLATE_BACKGROUND_WORKERS = 3
try:
    SEARCH_RELAX_MIN = max(1, min(20, int(os.environ.get("SEARCH_RELAX_MIN", "1"))))
except ValueError:
    SEARCH_RELAX_MIN = 3

# Translate the languages with the highest news volume first. The rest warm
# in the background and are picked up by the frontend's automatic retry.
_LANGUAGE_PRIORITY = (
    "en", "zh", "ru", "es", "pt", "fr", "de", "ar", "it", "tr",
    "uk", "ja", "ko", "fa", "hi", "id", "vi", "th", "he", "zh-Hant",
)

_ENV_LANGUAGES = {
    code.strip()
    for code in os.environ.get("SEARCH_TRANSLATE_LANGS", "").split(",")
    if code.strip()
}
TARGET_LANGUAGES = tuple(
    code for code in LANGUAGES
    if not _ENV_LANGUAGES or code in _ENV_LANGUAGES
)

_TRAILING = " \t\r\n\"“”'。！？!?.,;；:："
_STOPWORDS = {
    # Latin / Cyrillic / Arabic / Persian / Turkish / Vietnamese / Hebrew / Hindi
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "by", "for",
    "from", "with", "is", "are", "was", "were", "be", "this", "that",
    "el", "la", "los", "las", "de", "del", "en", "y", "o", "un", "una",
    "le", "les", "du", "des", "et", "au", "aux", "une",
    "der", "die", "das", "dem", "den", "im", "am", "und", "oder", "ein", "eine",
    "do", "da", "dos", "das", "em", "no", "na", "um", "uma",
    "il", "lo", "gli", "di", "della", "e",
    "в", "во", "на", "и", "с", "со", "по", "к", "ко", "о", "об", "от", "до",
    "за", "из", "у", "не", "для", "при",
    "і", "й", "з", "зі", "від", "та",
    "في", "من", "على", "إلى", "و", "ب", "ل", "عن",
    "در", "از", "به", "با", "برای", "که", "این", "آن",
    "ve", "ile", "için", "bir", "bu", "da", "de", "ve",
    "dan", "di", "untuk", "dari", "yang", "ke", "pada",
    "và", "của", "ở", "tại", "trong", "với", "cho",
    "של", "על", "עם", "את", "ב", "ל", "ה",
    "में", "का", "के", "की", "और", "से", "पर", "को",
}
_CJK_PARTICLES = set("的了在是与和及对为中将这些那有")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().strip(_TRAILING)


def _prefix(token: str) -> str:
    """Crude but effective stemming for inflected Latin/Cyrillic/Arabic words."""
    if len(token) >= 6:
        cut = max(4, int(len(token) * 0.65))
        if cut < len(token):
            return token[:cut]
    return token


def _has_cjk_or_thai(text: str) -> bool:
    return bool(re.search(r"[぀-ヿ㐀-鿿豈-﫿฀-๿]", text))


def _load_cjk_vocab() -> tuple[str, ...]:
    """Known Chinese/Japanese/Thai place/topic/person/lexicon terms."""
    terms: set[str] = set()

    def add(value: str) -> None:
        term = _normalize(value)
        if len(term) >= 2 and _has_cjk_or_thai(term):
            terms.add(term.casefold())

    try:
        gazetteer = customization.read_json("gazetteer")
        for country in gazetteer.get("countries", {}).values():
            for key in ("label_zh", "aliases"):
                value = country.get(key)
                if isinstance(value, list):
                    for item in value:
                        add(item)
                elif value:
                    add(value)
        for section in ("places", "actors", "topics"):
            for entry in gazetteer.get(section, []):
                if entry.get("label_zh"):
                    add(entry["label_zh"])
                for alias in entry.get("aliases", []):
                    add(alias)
        lexicon = customization.read_json("lexicon")
        for languages in lexicon.values():
            for language, words in languages.items():
                if language in ("zh", "zh-Hant", "ja", "th"):
                    for word in words:
                        add(word)
    except Exception:
        pass
    return tuple(sorted(terms, key=lambda item: (-len(item), item)))


_CJK_VOCAB: tuple[str, ...] | None = None


def _cjk_vocab() -> tuple[str, ...]:
    global _CJK_VOCAB
    if _CJK_VOCAB is None:
        _CJK_VOCAB = _load_cjk_vocab()
    return _CJK_VOCAB


def _vocab_terms(text: str) -> list[str]:
    """Pick up to four known terms, preferring long non-overlapping matches."""
    matches: list[tuple[int, int, str]] = []
    lowered = text.casefold()
    for term in _cjk_vocab():
        start = lowered.find(term)
        if start >= 0:
            matches.append((start, start + len(term), term))
    matches.sort(key=lambda item: (-(item[1] - item[0]), item[0]))
    selected: list[str] = []
    occupied: list[tuple[int, int]] = []
    for start, end, term in matches:
        if any(not (end <= used_start or start >= used_end) for used_start, used_end in occupied):
            continue
        selected.append(term)
        occupied.append((start, end))
        if len(selected) >= 4:
            break
    selected.sort(key=lambda term: lowered.find(term))
    return selected


def _cjk_chunks(text: str) -> list[str]:
    chars = [char for char in text if not char.isspace()]
    chunks: list[str] = []
    for index in range(0, len(chars), 2):
        chunk = "".join(chars[index:index + 2])
        if len(chunk) != 2 or not _has_cjk_or_thai(chunk):
            continue
        if chunk[0] in _CJK_PARTICLES or chunk[1] in _CJK_PARTICLES:
            continue
        if chunk not in chunks:
            chunks.append(chunk)
        if len(chunks) >= 4:
            break
    return chunks


_ALIAS_INDEX: dict[str, dict] | None = None


def _load_alias_index() -> dict[str, dict]:
    """Build a compact alias -> entity index from the event gazetteer.

    This is deliberately local and offline: known people, places, countries
    and event topics can expand across languages even when the translation
    provider is slow or rate-limited.
    """
    index: dict[str, dict] = {}

    def add(alias: str | None, entry: dict) -> None:
        value = _normalize(alias)
        if not value:
            return
        key = value.casefold()
        if len(key) < 2:
            return
        # Avoid treating common two-letter Latin words ("us", "uk") as names.
        if not _has_cjk_or_thai(key) and len(key) < 3:
            return
        index.setdefault(key, entry)

    try:
        gazetteer = customization.read_json("gazetteer")
        for code, item in (gazetteer.get("countries") or {}).items():
            aliases = [item.get("label_zh")] + list(item.get("aliases") or [])
            entry = {
                "kind": "country",
                "id": code,
                "label": item.get("label_zh") or code,
                "aliases": aliases,
            }
            for alias in aliases:
                add(alias, entry)
        for section, kind in (("places", "place"), ("actors", "actor"), ("topics", "topic")):
            for item in gazetteer.get(section) or []:
                aliases = [item.get("label_zh")] + list(item.get("aliases") or [])
                entry = {
                    "kind": kind,
                    "id": item.get("id") or item.get("label_zh") or "",
                    "label": item.get("label_zh") or item.get("id") or "",
                    "aliases": aliases,
                }
                for alias in aliases:
                    add(alias, entry)
    except Exception:
        pass
    return index


def _alias_index() -> dict[str, dict]:
    global _ALIAS_INDEX
    if _ALIAS_INDEX is None:
        _ALIAS_INDEX = _load_alias_index()
    return _ALIAS_INDEX


def _alias_entries(query: str) -> list[dict]:
    lowered = query.casefold()
    found: list[tuple[int, dict]] = []
    for alias, entry in _alias_index().items():
        if _has_cjk_or_thai(alias):
            if alias not in lowered:
                continue
        else:
            pattern = r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"
            if not re.search(pattern, lowered):
                continue
        found.append((len(alias), entry))
    found.sort(key=lambda pair: -pair[0])
    entries: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for _, entry in found:
        key = (str(entry.get("kind") or ""), str(entry.get("id") or ""))
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
        if len(entries) >= 6:
            break
    return entries


def _contains_anchor(text: str, anchors: list[str]) -> bool:
    lowered = text.casefold()
    for anchor in anchors:
        value = anchor.casefold()
        if not value:
            continue
        if _has_cjk_or_thai(value):
            if value in lowered:
                return True
            continue
        if value in lowered:
            return True
        # Machine translation often truncates inflection: "Тибе" for "Тибет".
        if len(value) >= 4 and value[:4] in lowered:
            return True
    return False


def _alias_variants(query: str, source: str) -> tuple[list[dict], list[str], list[str]]:
    """Return local multilingual variants and anchor terms for known entities.

    When a query contains a specific place/person/country, generic topic
    aliases (e.g. "earthquake") are suppressed; otherwise a query such as
    "Tibet earthquake" would match every earthquake in the corpus.
    """
    variants: list[dict] = []
    labels: list[str] = []
    anchors: list[str] = []
    seen = {query.casefold()}
    entries = _alias_entries(query)
    specific = [entry for entry in entries if entry.get("kind") != "topic"]
    if specific:
        entries = specific
    for entry in entries:
        for alias in entry.get("aliases") or []:
            value = _normalize(alias)
            if value:
                anchors.append(value)
        label = str(entry.get("label") or entry.get("id") or "").strip()
        if label:
            labels.append(label)
        for alias in entry.get("aliases") or []:
            text = _normalize(alias)
            key = text.casefold()
            if not text or len(text) < 2 or key in seen:
                continue
            language = detect_language(text) or source
            variant = make_variant(text, language)
            variant["origin"] = "alias"
            variant["alias_id"] = entry.get("id") or ""
            variant["alias_label"] = label
            variants.append(variant)
            seen.add(key)
            if len(variants) >= 12:
                break
        if len(variants) >= 12:
            break
    return variants, labels, anchors


def terms_for_variant(text: str, language: str, stem: bool = True) -> list[str]:
    """Return search terms for one translated query variant.

    Spaced languages get significant tokens. Source/alias queries use a
    conservative prefix stem so inflections still match; machine translations
    use full tokens to avoid false positives such as "Agen" matching
    "agencies" or "Bank" matching "West Bank".
    Chinese/Japanese/Thai use known event vocabulary, then 2-character chunks
    as a fallback when vocabulary matching yields fewer than two terms.
    """
    text = _normalize(text)
    if not text:
        return []
    if language in NO_SPACE_LANGUAGES:
        terms = _vocab_terms(text)
        if len(terms) < 2 and language in CJK_LANGUAGES:
            for chunk in _cjk_chunks(text):
                if chunk not in terms:
                    terms.append(chunk)
                if len(terms) >= 4:
                    break
        return terms[:4]

    terms: list[str] = []
    for token in re.findall(r"[^\W_]+", text, re.UNICODE):
        key = token.casefold()
        if len(token) <= 2 or key in _STOPWORDS:
            continue
        value = _prefix(token) if stem else key
        if value not in terms:
            terms.append(value)
        if len(terms) >= 4:
            break
    return terms


def make_variant(text: str, language: str, stem: bool = True) -> dict:
    return {
        "language": language,
        "text": _normalize(text),
        "terms": terms_for_variant(text, language, stem=stem),
    }


def _translate_one(target: str, text: str, source: str) -> tuple[str, dict]:
    conn = connect()
    try:
        return target, translate(conn, text, target, source)
    except Exception as exc:  # pragma: no cover - defensive
        return target, {"ok": False, "error": str(exc)[:160]}
    finally:
        conn.close()


def _warm_translations(targets: list[str], text: str, source: str) -> None:
    """Populate the translation cache after the interactive search returns."""
    if not targets:
        return
    # Give the synchronous batch a small head start so MyMemory is not
    # overwhelmed by 19 simultaneous requests.
    time.sleep(0.8)
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=SEARCH_TRANSLATE_BACKGROUND_WORKERS
    ) as pool:
        futures = [pool.submit(_translate_one, target, text, source) for target in targets]
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception:
                pass


def _ordered_targets(source: str) -> list[str]:
    ordered = [
        code for code in _LANGUAGE_PRIORITY
        if code in TARGET_LANGUAGES and code != source
    ]
    ordered.extend(
        code for code in TARGET_LANGUAGES
        if code not in _LANGUAGE_PRIORITY and code != source
    )
    return ordered


def expand_search(filters: dict) -> dict | None:
    """Translate the query and attach search variants to ``filters``.

    Three layers of resilience:
    1. Known gazetteer entities expand locally into multilingual aliases.
    2. The highest-volume languages are translated synchronously under a
       deadline; the rest warm in the background for the next retry.
    3. The API can relax strict AND matching when a query is too narrow.

    Returns a small metadata object for the API. The private ``_variants`` and
    ``_search_meta`` keys are consumed by db._build_where and stripped before
    the filters object is returned to clients.
    """
    q = _normalize(filters.get("q") or "")
    if not q:
        filters.pop("_variants", None)
        filters.pop("_search_meta", None)
        return None

    source = detect_language(q)
    variants = [make_variant(q, source)]
    variants[0]["origin"] = "source"
    alias_variants, alias_labels, anchor_terms = _alias_variants(q, source)
    variants.extend(alias_variants)
    meta = {
        "enabled": SEARCH_TRANSLATE,
        "source_language": source,
        "source_language_label": LANGUAGES.get(source, source),
        "languages": [],
        "failed": [],
        "provider_labels": [],
        "attempted": 0,
        "translated_count": 0,
        "partial": False,
        "timed_out": False,
        "elapsed_ms": 0,
        "alias_count": len(alias_variants),
        "alias_expanded": list(dict.fromkeys(label for label in alias_labels if label)),
        "anchor_rejected": 0,
        "weak_rejected": 0,
        "relaxed": False,
        "strict_total": None,
        "relaxed_total": None,
        "sync_limit": SEARCH_TRANSLATE_SYNC_LIMIT,
        "deferred": 0,
    }

    if not SEARCH_TRANSLATE or len(q) < 2:
        filters["_variants"] = variants
        filters["_search_meta"] = meta
        return meta

    targets = _ordered_targets(source)
    meta["attempted"] = len(targets)
    started = time.monotonic()
    results: dict[str, dict] = {}

    # Cached targets return instantly. Only missing languages consume the
    # network budget; repeated searches therefore stay fast.
    cache_conn = connect()
    try:
        for target in targets:
            hit = cached_translation(cache_conn, q, target, source)
            if hit:
                results[target] = hit
    finally:
        cache_conn.close()

    sync_targets = [
        target for target in targets[:SEARCH_TRANSLATE_SYNC_LIMIT]
        if target not in results
    ]
    deferred_targets = [
        target for target in targets[SEARCH_TRANSLATE_SYNC_LIMIT:]
        if target not in results
    ]
    meta["deferred"] = len(deferred_targets)
    timed_out = False
    if sync_targets:
        deadline = SEARCH_TRANSLATE_CACHED_DEADLINE if results else SEARCH_TRANSLATE_DEADLINE
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=SEARCH_TRANSLATE_WORKERS)
        futures = {pool.submit(_translate_one, target, q, source): target for target in sync_targets}
        try:
            for future in concurrent.futures.as_completed(futures, timeout=deadline):
                target = futures[future]
                try:
                    _, result = future.result()
                except Exception:
                    continue
                results[target] = result
        except concurrent.futures.TimeoutError:
            timed_out = True
        finally:
            # Keep running futures alive: they finish in the background and
            # populate the translation cache for the next search.
            pool.shutdown(wait=False, cancel_futures=False)

    if deferred_targets:
        threading.Thread(
            target=_warm_translations,
            args=(deferred_targets, q, source),
            daemon=True,
            name="search-translate-warmup",
        ).start()

    source_terms = variants[0].get("terms") or []
    min_terms = 2 if len(source_terms) >= 2 else 1
    seen = {str(variant.get("text") or "").casefold() for variant in variants}
    providers: set[str] = set()
    for target in targets:
        result = results.get(target)
        if not result:
            continue
        if not result.get("ok"):
            meta["failed"].append(target)
            continue
        translated = _normalize(result.get("translation") or "")
        if not translated:
            meta["failed"].append(target)
            continue
        provider_label = result.get("provider_label") or PROVIDER_LABELS.get(result.get("provider") or "", "")
        if provider_label:
            providers.add(provider_label)
        if anchor_terms and not _contains_anchor(translated, anchor_terms):
            meta["anchor_rejected"] += 1
            continue
        variant = make_variant(translated, target, stem=False)
        pieces = [
            piece for piece in re.findall(r"[^\W_]+", translated, re.UNICODE)
            if len(piece) > 1
        ]
        if max(len(variant.get("terms") or []), len(pieces)) < min_terms:
            meta["weak_rejected"] += 1
            continue
        key = translated.casefold()
        if key in seen:
            continue
        seen.add(key)
        variant["origin"] = "translation"
        variants.append(variant)
        meta["languages"].append({"code": target, "label": LANGUAGES.get(target, target)})
        if len(variants) >= MAX_VARIANTS:
            break

    meta["translated_count"] = len(meta["languages"])
    meta["provider_labels"] = sorted(providers)
    meta["partial"] = bool(meta["failed"]) or len(results) < len(targets)
    meta["timed_out"] = timed_out or len(results) < len(targets)
    meta["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    filters["_variants"] = variants
    filters["_search_meta"] = meta
    return meta


def reset() -> None:
    global _CJK_VOCAB, _ALIAS_INDEX
    _CJK_VOCAB = None
    _ALIAS_INDEX = None
