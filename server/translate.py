"""Translation provider chain.

The selected provider is used for both manual and automatic translation.
Selecting ``auto`` means a simple free chain:
1. LibreTranslate (if configured).
2. MyMemory public API (no key).
3. Local Ollama (private but usually slow).

Optional paid/API-key providers: DeepL, Google Cloud Translation, Azure
Translator, OpenAI-compatible chat APIs, Baidu Translate, Youdao and a generic
custom HTTP endpoint.  Provider keys are stored by ``customization.py`` in
``data/customization.json`` and are never returned by the read API or the
default export.

Environment variables remain supported for deployment.  See
``translation_specs.py`` for the field names and env names.
"""
from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from functools import partial
from urllib.parse import urlsplit

import customization
from db import utcnow
from taxonomy import detect_language
from translation_specs import (
    PROVIDER_IDS,
    PROVIDER_SPECS,
    env_layer,
    is_ready,
    legacy_layer,
    merge_config,
)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3-vl:8b")
LIBRE_URL = os.environ.get("LIBRETRANSLATE_URL", "").rstrip("/")
LIBRE_KEY = os.environ.get("LIBRETRANSLATE_API_KEY", "")
TRANSLATE_PROVIDER = os.environ.get("TRANSLATE_PROVIDER", "auto").lower()
MAX_CHARS = 2000
MYMEMORY_MAX = 500
USER_AGENT = "GlobalNewsTimeline/1.0 (local news timeline)"

PROMPT = """You are a professional news translator. Translate the following news headline and snippet into {language}.
Rules:
- Output only the translation, no explanations or quotation marks.
- Preserve proper nouns, numbers and place names; use the standard Chinese name when one exists.
- Keep it concise and natural, suitable for a news timeline.

Text:
{text}"""

CHAT_PROMPT = """You are a professional news translator. Translate the user's news headline or snippet into {language}.
Rules:
- Output only the translation, no explanations or quotation marks.
- Preserve proper nouns, numbers and place names; use the standard name when one exists.
- Keep it concise and natural, suitable for a news timeline."""

SOURCE_CODES = {
    "zh": "zh-CN", "zh-Hant": "zh-TW", "en": "en", "ja": "ja", "ko": "ko",
    "ru": "ru", "es": "es", "fr": "fr", "de": "de", "ar": "ar", "pt": "pt",
    "tr": "tr", "hi": "hi", "id": "id", "vi": "vi", "th": "th", "it": "it",
    "fa": "fa", "he": "he", "uk": "uk",
}
TARGET_CODES = {"zh": "zh-CN", "zh-Hant": "zh-TW"}
LANGUAGE_NAMES = {
    "zh": "Simplified Chinese", "zh-Hant": "Traditional Chinese", "en": "English",
    "ja": "Japanese", "ko": "Korean", "ru": "Russian", "es": "Spanish",
    "fr": "French", "de": "German", "ar": "Arabic", "pt": "Portuguese",
    "tr": "Turkish", "hi": "Hindi", "id": "Indonesian", "vi": "Vietnamese",
    "th": "Thai", "it": "Italian", "fa": "Persian", "he": "Hebrew",
    "uk": "Ukrainian",
}
DEEPL_TARGET = {
    "zh": "ZH", "zh-Hant": "ZH-HANT", "en": "EN", "ja": "JA", "ko": "KO",
    "ru": "RU", "es": "ES", "fr": "FR", "de": "DE", "ar": "AR", "pt": "PT",
    "tr": "TR", "hi": "HI", "id": "ID", "vi": "VI", "th": "TH", "it": "IT",
    "fa": "FA", "he": "HE", "uk": "UK",
}
DEEPL_SOURCE = dict(DEEPL_TARGET)
DEEPL_SOURCE["zh-Hant"] = "ZH"
AZURE_TARGET = {
    "zh": "zh-Hans", "zh-Hant": "zh-Hant", "en": "en", "ja": "ja", "ko": "ko",
    "ru": "ru", "es": "es", "fr": "fr", "de": "de", "ar": "ar", "pt": "pt",
    "tr": "tr", "hi": "hi", "id": "id", "vi": "vi", "th": "th", "it": "it",
    "fa": "fa", "he": "he", "uk": "uk",
}
AZURE_SOURCE = dict(AZURE_TARGET)
BAIDU_CODES = {
    "zh": "zh", "zh-Hant": "cht", "en": "en", "ja": "jp", "ko": "kor",
    "ru": "ru", "es": "spa", "fr": "fra", "de": "de", "ar": "ara", "pt": "pt",
    "tr": "tr", "hi": "hi", "id": "id", "vi": "vie", "th": "th", "it": "it",
    "fa": "fa", "he": "he", "uk": "ukr",
}
YOUDAO_CODES = {
    "zh": "zh-CHS", "zh-Hant": "zh-CHT", "en": "en", "ja": "ja", "ko": "ko",
    "ru": "ru", "es": "es", "fr": "fr", "de": "de", "ar": "ar", "pt": "pt",
    "tr": "tr", "hi": "hi", "id": "id", "vi": "vi", "th": "th", "it": "it",
    "fa": "fa", "he": "he", "uk": "uk",
}


class TranslationError(RuntimeError):
    pass


def _overlay_provider(overrides: dict, provider_id: str) -> dict:
    providers = overrides.get("providers")
    if isinstance(providers, dict):
        value = providers.get(provider_id)
        if isinstance(value, dict):
            return value
    return {}


def _provider_values(
    overrides: dict, provider_id: str, module_layer: dict | None = None
) -> dict:
    return merge_config(
        provider_id,
        env_layer(provider_id),
        module_layer or {},
        legacy_layer(provider_id, overrides),
        _overlay_provider(overrides, provider_id),
    )


def settings() -> dict:
    """Resolve translation settings from the GUI overlay, then env/defaults."""
    overrides = customization.translate_overrides()
    values = {"provider": str(TRANSLATE_PROVIDER).lower()}
    if overrides.get("provider"):
        values["provider"] = str(overrides["provider"]).lower()
    if values["provider"] not in ("auto", *PROVIDER_IDS):
        values["provider"] = "auto"
    module_layers = {
        "libre": {"url": LIBRE_URL, "key": LIBRE_KEY},
        "ollama": {"url": OLLAMA_URL, "model": OLLAMA_MODEL},
    }
    values["providers"] = {
        provider_id: _provider_values(
            overrides, provider_id, module_layers.get(provider_id)
        )
        for provider_id in PROVIDER_IDS
    }
    # Compatibility aliases used by older callers/tests.
    values["libre_url"] = values["providers"]["libre"]["url"]
    values["libre_key"] = values["providers"]["libre"]["key"]
    values["ollama_url"] = values["providers"]["ollama"]["url"]
    values["ollama_model"] = values["providers"]["ollama"]["model"]
    return values


PROVIDER_LABELS = {
    provider_id: spec["label"]
    for provider_id, spec in PROVIDER_SPECS.items()
}


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


def _request_json(request: urllib.request.Request, timeout: float) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:240]
        except Exception:
            pass
        raise TranslationError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise TranslationError(f"网络错误：{exc.reason}") from exc
    try:
        body = json.loads(raw)
    except Exception as exc:
        raise TranslationError("接口返回的不是 JSON") from exc
    if not isinstance(body, dict) and not isinstance(body, list):
        raise TranslationError("接口返回格式异常")
    return body


def _post_json(url: str, payload, headers: dict | None = None, timeout: float = 20) -> dict:
    merged = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    merged.update(headers or {})
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=merged,
        method="POST",
    )
    return _request_json(request, timeout)


def _post_form(url: str, fields: dict, headers: dict | None = None, timeout: float = 20) -> dict:
    merged = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    merged.update(headers or {})
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode("utf-8"),
        headers=merged,
        method="POST",
    )
    return _request_json(request, timeout)


def _get_json(url: str, headers: dict | None = None, timeout: float = 20) -> dict:
    merged = {"Accept": "application/json", "User-Agent": USER_AGENT}
    merged.update(headers or {})
    return _request_json(urllib.request.Request(url, headers=merged, method="GET"), timeout)


def _ollama(text: str, target: str, source: str, timeout: float = 20) -> tuple[str, str]:
    cfg = settings()["providers"]["ollama"]
    language = LANGUAGE_NAMES.get(target, target)
    payload = {
        "model": cfg["model"],
        "prompt": PROMPT.format(language=language, text=text),
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 360},
    }
    try:
        body = _post_json(cfg["url"] + "/api/generate", payload, timeout=timeout)
    except TranslationError as exc:
        raise TranslationError(f"Ollama 不可达：{exc}") from exc
    translated = (body.get("response") or "").strip()
    if not translated:
        raise TranslationError("Ollama 返回空译文")
    return translated, f"ollama:{cfg['model']}"


def _mymemory(text: str, target: str, source: str, timeout: float = 10) -> tuple[str, str]:
    cfg = settings()["providers"]["mymemory"]
    src = SOURCE_CODES.get(source, source or "en")
    tgt = TARGET_CODES.get(target, target)
    params = {"q": text[:MYMEMORY_MAX], "langpair": f"{src}|{tgt}"}
    if cfg.get("email"):
        params["de"] = cfg["email"]
    request = urllib.request.Request(
        "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(params),
        headers={"User-Agent": USER_AGENT},
    )
    try:
        body = _request_json(request, timeout)
    except TranslationError as exc:
        raise TranslationError(f"MyMemory 请求失败：{exc}") from exc
    translated = (body.get("responseData", {}).get("translatedText") or "").strip()
    status = body.get("responseStatus")
    upper = translated.upper()
    if not translated or status not in (200, "200") or "MYMEMORY WARNING" in upper:
        raise TranslationError("MyMemory 返回异常或达到免费额度")
    return translated, "mymemory"


def _libre(text: str, target: str, source: str, timeout: float = 35) -> tuple[str, str]:
    cfg = settings()["providers"]["libre"]
    if not cfg["url"]:
        raise TranslationError("未配置 LibreTranslate")
    payload = {
        "q": text[:1500],
        "source": SOURCE_CODES.get(source, source or "auto"),
        "target": TARGET_CODES.get(target, target),
        "format": "text",
    }
    if cfg.get("key"):
        payload["api_key"] = cfg["key"]
    try:
        body = _post_json(cfg["url"] + "/translate", payload, timeout=timeout)
    except TranslationError as exc:
        raise TranslationError(f"LibreTranslate 请求失败：{exc}") from exc
    translated = (body.get("translatedText") or "").strip()
    if not translated:
        raise TranslationError("LibreTranslate 返回空译文")
    return translated, "libre"


def _deepl(text: str, target: str, source: str, timeout: float = 20) -> tuple[str, str]:
    cfg = settings()["providers"]["deepl"]
    payload = {
        "text": [text[:1500]],
        "target_lang": DEEPL_TARGET.get(target, target.upper()),
    }
    if source and source != "auto":
        payload["source_lang"] = DEEPL_SOURCE.get(source, source.upper())
    headers = {"Authorization": f"DeepL-Auth-Key {cfg['key']}"}
    try:
        body = _post_json(cfg["endpoint"], payload, headers=headers, timeout=timeout)
    except TranslationError as exc:
        raise TranslationError(f"DeepL 请求失败：{exc}") from exc
    translations = body.get("translations") or []
    translated = (translations[0].get("text") if translations else "") or ""
    translated = translated.strip()
    if not translated:
        raise TranslationError("DeepL 返回空译文")
    return translated, "deepl"


def _google(text: str, target: str, source: str, timeout: float = 20) -> tuple[str, str]:
    cfg = settings()["providers"]["google"]
    payload = {
        "q": text[:1500],
        "target": TARGET_CODES.get(target, target),
        "format": "text",
    }
    if source and source != "auto":
        payload["source"] = SOURCE_CODES.get(source, source)
    url = cfg["endpoint"]
    separator = "&" if "?" in url else "?"
    url = url + separator + urllib.parse.urlencode({"key": cfg["key"]})
    try:
        body = _post_json(url, payload, timeout=timeout)
    except TranslationError as exc:
        raise TranslationError(f"Google 翻译请求失败：{exc}") from exc
    data = body.get("data") or {}
    translations = data.get("translations") or []
    translated = (translations[0].get("translatedText") if translations else "") or ""
    translated = html.unescape(translated).strip()
    if not translated:
        raise TranslationError("Google 翻译返回空译文")
    return translated, "google"


def _azure(text: str, target: str, source: str, timeout: float = 20) -> tuple[str, str]:
    cfg = settings()["providers"]["azure"]
    params = {
        "api-version": "3.0",
        "to": AZURE_TARGET.get(target, target),
    }
    if source and source != "auto":
        params["from"] = AZURE_SOURCE.get(source, source)
    url = cfg["endpoint"].rstrip("/") + "/translate?" + urllib.parse.urlencode(params)
    headers = {
        "Ocp-Apim-Subscription-Key": cfg["key"],
        "Ocp-Apim-Subscription-Region": cfg["region"],
    }
    try:
        body = _post_json(url, [{"Text": text[:1500]}], headers=headers, timeout=timeout)
    except TranslationError as exc:
        raise TranslationError(f"Azure 翻译请求失败：{exc}") from exc
    translated = ""
    if isinstance(body, list) and body:
        translations = body[0].get("translations") or []
        if translations:
            translated = translations[0].get("text") or ""
    translated = translated.strip()
    if not translated:
        raise TranslationError("Azure 翻译返回空译文")
    return translated, "azure"


def _openai(text: str, target: str, source: str, timeout: float = 30) -> tuple[str, str]:
    cfg = settings()["providers"]["openai"]
    base = cfg["base_url"].rstrip("/")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    language = LANGUAGE_NAMES.get(target, target)
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": CHAT_PROMPT.format(language=language)},
            {"role": "user", "content": text[:1500]},
        ],
        "temperature": 0.1,
        "max_tokens": 800,
    }
    headers = {"Authorization": f"Bearer {cfg['key']}"}
    try:
        body = _post_json(url, payload, headers=headers, timeout=timeout)
    except TranslationError as exc:
        raise TranslationError(f"OpenAI 兼容接口请求失败：{exc}") from exc
    choices = body.get("choices") or []
    translated = ""
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        translated = (content or choices[0].get("text") or "").strip()
    if not translated:
        raise TranslationError("OpenAI 兼容接口返回空译文")
    return translated, f"openai:{cfg['model']}"


def _baidu(text: str, target: str, source: str, timeout: float = 20) -> tuple[str, str]:
    cfg = settings()["providers"]["baidu"]
    q = text[:1500]
    salt = str(int(time.time() * 1000))
    sign = hashlib.md5(
        (cfg["appid"] + q + salt + cfg["key"]).encode("utf-8")
    ).hexdigest()
    fields = {
        "q": q,
        "from": BAIDU_CODES.get(source, source or "auto"),
        "to": BAIDU_CODES.get(target, target),
        "appid": cfg["appid"],
        "salt": salt,
        "sign": sign,
    }
    try:
        body = _post_form(cfg["endpoint"], fields, timeout=timeout)
    except TranslationError as exc:
        raise TranslationError(f"百度翻译请求失败：{exc}") from exc
    error_code = body.get("error_code")
    if error_code not in (None, "0", 0):
        raise TranslationError(f"百度翻译错误 {error_code}: {body.get('error_msg') or ''}")
    results = body.get("trans_result") or []
    translated = (results[0].get("dst") if results else "") or ""
    translated = translated.strip()
    if not translated:
        raise TranslationError("百度翻译返回空译文")
    return translated, "baidu"


def _youdao(text: str, target: str, source: str, timeout: float = 20) -> tuple[str, str]:
    cfg = settings()["providers"]["youdao"]
    q = text[:1500]
    salt = str(uuid.uuid4())
    curtime = str(int(time.time()))
    truncated = q if len(q) <= 20 else q[:10] + str(len(q)) + q[-10:]
    sign = hashlib.sha256(
        (cfg["app_key"] + truncated + salt + curtime + cfg["app_secret"]).encode("utf-8")
    ).hexdigest()
    fields = {
        "q": q,
        "from": YOUDAO_CODES.get(source, source or "auto"),
        "to": YOUDAO_CODES.get(target, target),
        "appKey": cfg["app_key"],
        "salt": salt,
        "sign": sign,
        "signType": "v3",
        "curtime": curtime,
    }
    try:
        body = _post_form(cfg["endpoint"], fields, timeout=timeout)
    except TranslationError as exc:
        raise TranslationError(f"有道翻译请求失败：{exc}") from exc
    error_code = body.get("errorCode")
    if error_code not in (None, "0", 0):
        raise TranslationError(f"有道翻译错误 {error_code}")
    translations = body.get("translation") or []
    translated = (translations[0] if translations else "") or ""
    translated = str(translated).strip()
    if not translated:
        raise TranslationError("有道翻译返回空译文")
    return translated, "youdao"


def _dig(data, path: str):
    current = data
    for part in (path or "").replace("[", ".").replace("]", "").split("."):
        if not part:
            continue
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(part)
    return current


def _fill_url(template: str, values: dict) -> str:
    out = template
    for key in ("text", "source", "target", "key"):
        out = out.replace("{{" + key + "}}", urllib.parse.quote(str(values.get(key, "")), safe=""))
    return out


def _custom(text: str, target: str, source: str, timeout: float = 20) -> tuple[str, str]:
    cfg = settings()["providers"]["custom"]
    values = {
        "text": text[:1500],
        "source": source or "auto",
        "target": target,
        "key": cfg.get("key") or "",
    }
    url = _fill_url(cfg["url"], values)
    method = (cfg.get("method") or "POST").upper()
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    raw_headers = (cfg.get("headers") or "").strip()
    if raw_headers:
        raw_headers = raw_headers.replace("{{key}}", values["key"])
        try:
            extra = json.loads(raw_headers)
        except Exception as exc:
            raise TranslationError("自定义请求头不是合法 JSON") from exc
        if isinstance(extra, dict):
            headers.update({str(k): str(v) for k, v in extra.items()})
    if method == "GET":
        if "{{" not in cfg["url"]:
            separator = "&" if "?" in url else "?"
            url += separator + urllib.parse.urlencode(
                {"q": values["text"], "source": values["source"], "target": values["target"]}
            )
        try:
            body = _get_json(url, headers=headers, timeout=timeout)
        except TranslationError as exc:
            raise TranslationError(f"自定义接口请求失败：{exc}") from exc
    else:
        raw_body = (cfg.get("body") or "").strip()
        if raw_body:
            filled = raw_body
            for key in ("text", "source", "target"):
                filled = filled.replace(
                    "{{" + key + "}}", json.dumps(str(values[key]), ensure_ascii=False)
                )
            filled = filled.replace("{{key}}", json.dumps(values["key"], ensure_ascii=False))
            try:
                payload = json.loads(filled)
            except Exception as exc:
                raise TranslationError("自定义请求体不是合法 JSON") from exc
        else:
            payload = {
                "text": values["text"],
                "source": values["source"],
                "target": values["target"],
            }
        try:
            body = _post_json(url, payload, headers=headers, timeout=timeout)
        except TranslationError as exc:
            raise TranslationError(f"自定义接口请求失败：{exc}") from exc
    try:
        translated = str(_dig(body, cfg.get("result_path") or "translation")).strip()
    except Exception as exc:
        raise TranslationError(f"找不到响应路径：{cfg.get('result_path') or 'translation'}") from exc
    if not translated:
        raise TranslationError("自定义接口返回空译文")
    return translated, "custom"


PROVIDER_FUNCS = {
    "libre": _libre,
    "ollama": _ollama,
    "mymemory": _mymemory,
    "deepl": _deepl,
    "google": _google,
    "azure": _azure,
    "openai": _openai,
    "baidu": _baidu,
    "youdao": _youdao,
    "custom": _custom,
}


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


def _provider_ready(provider_id: str, cfg: dict) -> bool:
    if provider_id not in PROVIDER_SPECS:
        return False
    return is_ready(provider_id, cfg["providers"][provider_id])


def _chain(fast: bool = False) -> list[tuple[str, object]]:
    cfg = settings()
    provider = cfg["provider"]

    if provider == "auto":
        # "Auto" is a simple free chain, not a separate policy layer. Paid
        # providers are only used when explicitly selected as the main provider.
        if fast:
            chain: list[tuple[str, object]] = []
            if _provider_ready("libre", cfg):
                chain.append(("libre", partial(_libre, timeout=5)))
            if _provider_ready("mymemory", cfg):
                chain.append(("mymemory", partial(_mymemory, timeout=5)))
            return chain
        chain = []
        if _provider_ready("libre", cfg):
            chain.append(("libre", _libre))
        if _provider_ready("mymemory", cfg):
            chain.append(("mymemory", _mymemory))
        if _provider_ready("ollama", cfg):
            chain.append(("ollama", _ollama))
        return chain

    if not _provider_ready(provider, cfg):
        return []
    function = PROVIDER_FUNCS[provider]
    if not fast:
        return [(provider, function)]
    timeout = 5 if provider in ("libre", "mymemory") else (15 if provider == "ollama" else 8)
    return [(provider, partial(function, timeout=timeout))]


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
    digest = hashlib.sha1((source + "\0" + target + "\0" + text).encode("utf-8")).hexdigest()
    cached = _cache_get(conn, digest, target)
    return {"ok": True, **cached} if cached else None


def translate(
    conn: sqlite3.Connection,
    text: str,
    target: str = "zh",
    source: str | None = None,
    fast: bool = False,
) -> dict:
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "Empty text"}
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    source = source or detect_language(text)

    digest = hashlib.sha1((source + "\0" + target + "\0" + text).encode("utf-8")).hexdigest()
    cached = _cache_get(conn, digest, target)
    if cached:
        return {"ok": True, **cached}

    cfg = settings()
    chain = _chain(fast=fast)
    if not chain:
        provider = cfg["provider"]
        if provider in PROVIDER_SPECS and not _provider_ready(provider, cfg):
            error = (
                f"接口 {PROVIDER_LABELS[provider]} 尚未配置完整（缺少 API Key、地址或区域）。"
                "请在运行设置里补全后重试。"
            )
        elif provider == "auto":
            error = (
                "自动模式没有可用接口：请配置 LibreTranslate / Ollama，"
                "或直接选择一个翻译接口。"
            )
        else:
            error = "翻译失败。请检查接口地址、API Key、额度或网络。"
        return {"ok": False, "error": error, "providers": []}

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
            }
        except Exception as exc:
            errors.append(f"{PROVIDER_LABELS.get(provider, provider)}: {str(exc)[:160]}")
    return {
        "ok": False,
        "error": "翻译失败。请检查接口地址、API Key、额度或网络。",
        "providers": errors,
    }
