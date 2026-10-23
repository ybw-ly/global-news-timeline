"""Translation provider chain.

Fast mode (default):
1. An explicitly configured local/private LibreTranslate instance.
2. MyMemory public API (no key; usually returns in ~2 seconds).
3. Local Ollama (private fallback; often slow on 8B models).

Set TRANSLATE_LOCAL_FIRST=1 to restore local-first order, TRANSLATE_FALLBACK=0
to disable MyMemory, or TRANSLATE_PROVIDER=ollama to force local-only.
"""
from __future__ import annotations

import ipaddress
import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlsplit
from hashlib import sha1

from db import utcnow
from taxonomy import detect_language

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3-vl:8b")
LIBRE_URL = os.environ.get("LIBRETRANSLATE_URL", "").rstrip("/")
LIBRE_KEY = os.environ.get("LIBRETRANSLATE_API_KEY", "")
TRANSLATE_PROVIDER = os.environ.get("TRANSLATE_PROVIDER", "auto").lower()
TRANSLATE_FALLBACK = os.environ.get("TRANSLATE_FALLBACK", "1").lower() not in (
    "0", "false", "off", "no",
)
TRANSLATE_FREE_ONLY = os.environ.get("TRANSLATE_FREE_ONLY", "1").lower() not in (
    "0", "false", "off", "no",
)
TRANSLATE_LOCAL_FIRST = os.environ.get("TRANSLATE_LOCAL_FIRST", "0").lower() not in (
    "0", "false", "off", "no",
)
MAX_CHARS = 2000
MYMEMORY_MAX = 500

PROVIDER_LABELS = {
    "ollama": "本地 Ollama（免费）",
    "mymemory": "MyMemory 免费接口",
    "libre": "LibreTranslate（自建）",
}

PROMPT = """You are a professional news translator. Translate the following news headline and snippet into {language}.
Rules:
- Output only the translation, no explanations or quotation marks.
- Preserve proper nouns, numbers and place names; use the standard Chinese name when one exists.
- Keep it concise and natural, suitable for a news timeline.

Text:
{text}"""

SOURCE_CODES = {
    "zh": "zh-CN", "zh-Hant": "zh-TW", "en": "en", "ja": "ja", "ko": "ko",
    "ru": "ru", "es": "es", "fr": "fr", "de": "de", "ar": "ar", "pt": "pt",
    "tr": "tr", "hi": "hi", "id": "id", "vi": "vi", "th": "th", "it": "it",
    "fa": "fa", "he": "he", "uk": "uk",
}
TARGET_CODES = {"zh": "zh-CN", "zh-Hant": "zh-TW"}


class TranslationError(RuntimeError):
    pass


def _cache_get(conn: sqlite3.Connection, text_hash: str, target: str) -> dict | None:
    row = conn.execute(
        "SELECT translated_text, model FROM translations WHERE text_hash=? AND target=?",
        (text_hash, target),
    ).fetchone()
    if not row:
        return None
    stored = row["model"] or ""
    provider = stored.split(":", 1)[0] if stored else "cache"
    return {
        "translation": row["translated_text"],
        "model": stored,
        "provider": provider,
        "provider_label": PROVIDER_LABELS.get(provider, provider),
        "cached": True,
    }


def _cache_put(
    conn: sqlite3.Connection,
    text_hash: str,
    target: str,
    source_text: str,
    translated: str,
    model: str,
) -> None:
    conn.execute(
        """
        INSERT INTO translations(text_hash, target, source_text, translated_text, model, created_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(text_hash, target) DO UPDATE SET
            translated_text=excluded.translated_text, model=excluded.model,
            created_at=excluded.created_at
        """,
        (text_hash, target, source_text, translated, model, utcnow()),
    )
    conn.commit()


def _ollama(text: str, target: str, source: str) -> tuple[str, str]:
    language = "Traditional Chinese" if target == "zh-Hant" else "Simplified Chinese"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": PROMPT.format(language=language, text=text),
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 360},
    }
    request = urllib.request.Request(
        OLLAMA_URL + "/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise TranslationError(f"Ollama 不可达：{exc.reason}") from exc
    translated = (body.get("response") or "").strip()
    if not translated:
        raise TranslationError("Ollama 返回空译文")
    return translated, f"ollama:{OLLAMA_MODEL}"


def _mymemory(text: str, target: str, source: str) -> tuple[str, str]:
    src = SOURCE_CODES.get(source, source or "en")
    tgt = TARGET_CODES.get(target, target)
    query = urllib.parse.urlencode(
        {"q": text[:MYMEMORY_MAX], "langpair": f"{src}|{tgt}"}
    )
    request = urllib.request.Request(
        "https://api.mymemory.translated.net/get?" + query,
        headers={"User-Agent": "GlobalNewsTimeline/1.0 (local news timeline)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise TranslationError(f"MyMemory 请求失败：{str(exc)[:120]}") from exc
    translated = (body.get("responseData", {}).get("translatedText") or "").strip()
    status = body.get("responseStatus")
    upper = translated.upper()
    if not translated or status not in (200, "200") or "MYMEMORY WARNING" in upper:
        raise TranslationError("MyMemory 返回异常或达到免费额度")
    return translated, "mymemory"


def _libre(text: str, target: str, source: str) -> tuple[str, str]:
    if not LIBRE_URL:
        raise TranslationError("未配置 LibreTranslate")
    payload = {
        "q": text[:1500],
        "source": SOURCE_CODES.get(source, source or "auto"),
        "target": TARGET_CODES.get(target, target),
        "format": "text",
    }
    if LIBRE_KEY:
        payload["api_key"] = LIBRE_KEY
    request = urllib.request.Request(
        LIBRE_URL + "/translate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise TranslationError(f"LibreTranslate 请求失败：{str(exc)[:120]}") from exc
    translated = (body.get("translatedText") or "").strip()
    if not translated:
        raise TranslationError("LibreTranslate 返回空译文")
    return translated, "libre"


def _is_local_url(url: str) -> bool:
    """True for localhost, private IPs and .local hostnames."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except Exception:
        return False
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_loopback or address.is_private
    except ValueError:
        return host.endswith(".local")


def _chain() -> list[tuple[str, object]]:
    # Free-only mode is fail-closed for external LibreTranslate. MyMemory's
    # anonymous endpoint is free (it returns an error when the free quota is
    # exhausted; it is never upgraded to a paid plan by this application).
    libre_allowed = bool(LIBRE_URL) and (
        not TRANSLATE_FREE_ONLY or _is_local_url(LIBRE_URL)
    )
    if TRANSLATE_PROVIDER == "ollama":
        return [("ollama", _ollama)]
    if TRANSLATE_PROVIDER == "mymemory":
        return [("mymemory", _mymemory)]
    if TRANSLATE_PROVIDER == "libre":
        return [("libre", _libre)] if libre_allowed else []
    if TRANSLATE_LOCAL_FIRST:
        chain: list[tuple[str, object]] = [("ollama", _ollama)]
        if libre_allowed:
            chain.append(("libre", _libre))
        if TRANSLATE_FALLBACK:
            chain.append(("mymemory", _mymemory))
        return chain

    # Fast default: local LibreTranslate is both private and fast, then the
    # anonymous MyMemory endpoint, then Ollama as a last resort. An 8B local
    # model can take tens of seconds to cold-start, so it must not block the
    # common case.
    chain = []
    if libre_allowed:
        chain.append(("libre", _libre))
    if TRANSLATE_FALLBACK:
        chain.append(("mymemory", _mymemory))
    chain.append(("ollama", _ollama))
    return chain


def cached_translation(
    conn: sqlite3.Connection, text: str, target: str = "zh", source: str | None = None
) -> dict | None:
    """Return a cached translation without touching the network."""
    text = (text or "").strip()
    if not text:
        return None
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    source = source or detect_language(text)
    digest = sha1((source + "\0" + target + "\0" + text).encode("utf-8")).hexdigest()
    cached = _cache_get(conn, digest, target)
    return {"ok": True, **cached} if cached else None


def translate(
    conn: sqlite3.Connection, text: str, target: str = "zh", source: str | None = None
) -> dict:
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "Empty text"}
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    source = source or detect_language(text)

    digest = sha1((source + "\0" + target + "\0" + text).encode("utf-8")).hexdigest()
    cached = _cache_get(conn, digest, target)
    if cached:
        return {"ok": True, **cached}

    chain = _chain()
    if not chain:
        return {
            "ok": False,
            "error": (
                "免费模式已阻止外部 LibreTranslate。请使用本地 Ollama、"
                "本地 LibreTranslate，或设置 TRANSLATE_FREE_ONLY=0 后自行承担费用。"
            ),
            "providers": [],
            "free_only": TRANSLATE_FREE_ONLY,
        }

    errors: list[str] = []
    for provider, function in chain:
        try:
            translated, model = function(text, target, source)  # type: ignore[operator]
            _cache_put(conn, digest, target, text, translated, model)
            return {
                "ok": True,
                "translation": translated,
                "model": model,
                "provider": provider,
                "provider_label": PROVIDER_LABELS.get(provider, provider),
                "cached": False,
                "free_only": TRANSLATE_FREE_ONLY,
            }
        except Exception as exc:
            errors.append(f"{PROVIDER_LABELS.get(provider, provider)}: {str(exc)[:160]}")
    return {
        "ok": False,
        "error": "翻译失败。可启动本地 Ollama，或检查免费翻译额度/网络。",
        "providers": errors,
        "free_only": TRANSLATE_FREE_ONLY,
    }
