"""Browser-editable configuration overlay.

Built-in JSON files under ``config/`` stay untouched.  Anything saved from the
browser is written to ``data/customization.json`` (override with
``CUSTOMIZATION_PATH``).  Loaders call :func:`read_json`, so GUI changes apply
without editing files or restarting the server.

The overlay is deliberately plain JSON: it can be exported, versioned or moved
between machines.  Write endpoints are protected in ``app.py`` by
``ADMIN_TOKEN`` or a loopback-only check.
"""
from __future__ import annotations

import copy
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from translation_specs import (
    PROVIDER_IDS,
    PROVIDER_SPECS,
    SECRET_KEYS,
    env_layer,
    is_ready,
    legacy_layer,
    merge_config,
    public_config,
    public_specs,
    strip_secrets,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PATH = Path(os.environ.get("CUSTOMIZATION_PATH", DATA / "customization.json"))

BUILTIN = {
    "feeds": ROOT / "config" / "feeds.json",
    "elections": ROOT / "config" / "elections.json",
    "quality": ROOT / "config" / "quality.json",
    "content_types": ROOT / "config" / "content_types.json",
    "lexicon": ROOT / "config" / "lexicon.json",
    "countries": ROOT / "config" / "countries.json",
    "gazetteer": ROOT / "config" / "gazetteer.json",
}
RESTART_REQUIRED = {"countries"}
MAX_BYTES = 8_000_000
FEED_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

DEFAULT_UI: dict[str, Any] = {
    "default_hours": 24,
    "default_content_type": "hard",
    "default_category": "all",
    "default_region": "all",
    "default_language": "all",
    "compact": False,
    "accent": "#76e0c2",
    "default_election": "auto",
    "auto_translate": False,
}

_LOCK = threading.RLock()
_CACHE: dict[str, Any] = {"overlay_mtime": None, "overlay": {}, "builtin": {}}


class ConfigError(ValueError):
    """Invalid configuration submitted from the browser."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_overlay() -> dict:
    try:
        mtime = PATH.stat().st_mtime
    except OSError:
        return {}
    with _LOCK:
        if _CACHE["overlay_mtime"] == mtime:
            return _CACHE["overlay"]
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    with _LOCK:
        _CACHE["overlay_mtime"] = mtime
        _CACHE["overlay"] = data
    return data


def _write_overlay(data: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, PATH)
    try:
        os.chmod(PATH, 0o600)
    except OSError:
        pass
    with _LOCK:
        _CACHE["overlay_mtime"] = None
        _CACHE["overlay"] = {}


def _check_name(name: str) -> None:
    if name not in BUILTIN:
        raise ConfigError(f"Unknown config section: {name}")


def read_json(name: str) -> Any:
    """Return the effective config, preferring the browser-saved override."""
    _check_name(name)
    overlay = _read_overlay()
    configs = overlay.get("configs")
    if isinstance(configs, dict) and name in configs:
        return copy.deepcopy(configs[name])

    path = BUILTIN[name]
    try:
        mtime = path.stat().st_mtime
    except OSError as exc:
        raise ConfigError(f"{name}: built-in config missing") from exc
    cached = _CACHE["builtin"].get(name)
    if cached and cached[0] == mtime:
        return copy.deepcopy(cached[1])
    data = json.loads(path.read_text(encoding="utf-8"))
    with _LOCK:
        _CACHE["builtin"][name] = (mtime, data)
    return copy.deepcopy(data)


def is_overridden(name: str) -> bool:
    _check_name(name)
    configs = _read_overlay().get("configs") or {}
    return isinstance(configs, dict) and name in configs


def _section_count(name: str, data: Any) -> int:
    if name == "feeds" and isinstance(data, dict):
        return len(data.get("feeds") or [])
    if name == "elections" and isinstance(data, dict):
        return len(data.get("elections") or [])
    if name == "quality" and isinstance(data, dict):
        return len(data.get("rules") or [])
    if isinstance(data, dict):
        return len(data)
    if isinstance(data, list):
        return len(data)
    return 0


def state() -> dict:
    overlay = _read_overlay()
    sections = {}
    for name in BUILTIN:
        data = read_json(name)
        sections[name] = {
            "overridden": is_overridden(name),
            "count": _section_count(name, data),
            "restart": name in RESTART_REQUIRED,
        }
    return {
        "sections": sections,
        "ui": get_ui(),
        "runtime": get_runtime(),
        "paths": {
            "overlay": str(PATH),
            "config_dir": str(ROOT / "config"),
        },
        "updated_at": overlay.get("updated_at", ""),
    }


def describe(name: str) -> dict:
    _check_name(name)
    return {
        "name": name,
        "overridden": is_overridden(name),
        "restart": name in RESTART_REQUIRED,
        "data": read_json(name),
    }


def _validate_feeds(data: Any) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("feeds"), list):
        raise ConfigError("feeds: expected an object with a feeds list")
    settings = data.get("settings", {})
    if not isinstance(settings, dict):
        raise ConfigError("feeds.settings must be an object")
    seen: set[str] = set()
    for index, feed in enumerate(data["feeds"]):
        label = f"feeds[{index}]"
        if not isinstance(feed, dict):
            raise ConfigError(f"{label}: must be an object")
        feed_id = str(feed.get("id") or "").strip()
        if not FEED_ID_RE.match(feed_id):
            raise ConfigError(f"{label}: invalid id {feed_id!r}")
        if feed_id in seen:
            raise ConfigError(f"{label}: duplicate id {feed_id!r}")
        seen.add(feed_id)
        if not str(feed.get("name") or "").strip():
            raise ConfigError(f"{label}: name is required")
        url = str(feed.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ConfigError(f"{label}: url must start with http:// or https://")
        if not str(feed.get("language") or "").strip():
            raise ConfigError(f"{label}: language is required")
        country = str(feed.get("country") or "").strip()
        if country and not re.match(r"^[A-Za-z]{2}$", country):
            raise ConfigError(f"{label}: country must be a 2-letter code")
        if "refresh_minutes" in feed:
            try:
                minutes = int(feed["refresh_minutes"])
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"{label}: refresh_minutes must be an integer") from exc
            if not 5 <= minutes <= 1440:
                raise ConfigError(f"{label}: refresh_minutes must be 5-1440")
        if "enabled" in feed and not isinstance(feed["enabled"], bool):
            raise ConfigError(f"{label}: enabled must be true/false")


def _validate_elections(data: Any) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("elections"), list):
        raise ConfigError("elections: expected an object with an elections list")
    seen: set[str] = set()
    for index, election in enumerate(data["elections"]):
        label = f"elections[{index}]"
        if not isinstance(election, dict):
            raise ConfigError(f"{label}: must be an object")
        election_id = str(election.get("id") or "").strip()
        if not election_id or election_id in seen:
            raise ConfigError(f"{label}: missing or duplicate id")
        seen.add(election_id)
        if not str(election.get("name_zh") or "").strip():
            raise ConfigError(f"{label}: name_zh is required")
        status = str(election.get("status") or "")
        if status not in ("upcoming", "live", "finished", "postponed"):
            raise ConfigError(f"{label}: status must be upcoming/live/finished/postponed")
        if not str(election.get("election_date") or "").strip():
            raise ConfigError(f"{label}: election_date is required")
        for key in (
            "timeline", "watchlist", "sources", "candidates", "scopes",
            "overseas", "result_summary", "status_facts",
        ):
            if key in election and not isinstance(election[key], list):
                raise ConfigError(f"{label}: {key} must be a list")
        if "polls" in election and election["polls"] is not None and not isinstance(election["polls"], dict):
            raise ConfigError(f"{label}: polls must be an object or null")
        if "adapter" in election and not isinstance(election["adapter"], dict):
            raise ConfigError(f"{label}: adapter must be an object")


def _validate_quality(data: Any) -> None:
    if not isinstance(data, dict):
        raise ConfigError("quality: expected an object")
    if "enabled" in data and not isinstance(data["enabled"], bool):
        raise ConfigError("quality.enabled must be true/false")
    rules = data.get("rules", [])
    if not isinstance(rules, list):
        raise ConfigError("quality.rules must be a list")
    for index, rule in enumerate(rules):
        label = f"quality.rules[{index}]"
        if not isinstance(rule, dict):
            raise ConfigError(f"{label}: must be an object")
        patterns = [rule.get(field) for field in ("title", "summary", "url") if rule.get(field)]
        if not patterns:
            raise ConfigError(f"{label}: needs title, summary or url pattern")
        for field in ("title", "summary", "url", "unless"):
            value = rule.get(field)
            if value:
                try:
                    re.compile(str(value))
                except re.error as exc:
                    raise ConfigError(f"{label}.{field}: invalid regex ({exc})") from exc


def _validate_ui(ui: Any) -> dict:
    if not isinstance(ui, dict):
        raise ConfigError("ui: expected an object")
    clean = dict(DEFAULT_UI)
    for key in list(clean):
        if key in ui:
            clean[key] = ui[key]
    try:
        hours = int(clean["default_hours"])
    except (TypeError, ValueError) as exc:
        raise ConfigError("ui.default_hours must be an integer") from exc
    if not 1 <= hours <= 720:
        raise ConfigError("ui.default_hours must be 1-720")
    clean["default_hours"] = hours
    if clean["default_content_type"] not in ("hard", "analysis", "opinion", "all"):
        raise ConfigError("ui.default_content_type must be hard/analysis/opinion/all")
    for key in ("default_category", "default_region", "default_language", "default_election"):
        if not isinstance(clean[key], str):
            raise ConfigError(f"ui.{key} must be a string")
    if not isinstance(clean["compact"], bool):
        raise ConfigError("ui.compact must be true/false")
    if not isinstance(clean["auto_translate"], bool):
        raise ConfigError("ui.auto_translate must be true/false")
    if not COLOR_RE.match(str(clean["accent"])):
        raise ConfigError("ui.accent must be a #RRGGBB color")
    return clean


def _validate(name: str, data: Any) -> None:
    try:
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name}: not JSON serializable") from exc
    if len(encoded) > MAX_BYTES:
        raise ConfigError(f"{name}: config is larger than {MAX_BYTES // 1_000_000} MB")
    if name == "feeds":
        _validate_feeds(data)
    elif name == "elections":
        _validate_elections(data)
    elif name == "quality":
        _validate_quality(data)
    elif not isinstance(data, (dict, list)):
        raise ConfigError(f"{name}: expected an object or list")


def save_config(name: str, data: Any) -> dict:
    _check_name(name)
    _validate(name, data)
    overlay = copy.deepcopy(_read_overlay())
    overlay.setdefault("format", "global-news-timeline-customization")
    overlay.setdefault("version", 1)
    overlay.setdefault("configs", {})[name] = data
    overlay["updated_at"] = _now()
    _write_overlay(overlay)
    reset_runtime_caches()
    return {"name": name, "overridden": True}


def reset_config(name: str) -> dict:
    _check_name(name)
    overlay = copy.deepcopy(_read_overlay())
    configs = overlay.get("configs")
    if isinstance(configs, dict):
        configs.pop(name, None)
        if not configs:
            overlay.pop("configs", None)
    overlay["updated_at"] = _now()
    _write_overlay(overlay)
    reset_runtime_caches()
    return {"name": name, "overridden": False}


def translate_overrides() -> dict:
    runtime = _read_overlay().get("runtime") or {}
    value = runtime.get("translation") if isinstance(runtime, dict) else None
    return dict(value) if isinstance(value, dict) else {}


def get_ui() -> dict:
    ui = dict(DEFAULT_UI)
    saved = _read_overlay().get("ui")
    if isinstance(saved, dict):
        for key in ui:
            if key in saved:
                ui[key] = saved[key]
    return ui


def save_ui(ui: dict) -> dict:
    merged = dict(get_ui())
    merged.update(ui or {})
    clean = _validate_ui(merged)
    overlay = copy.deepcopy(_read_overlay())
    overlay["ui"] = clean
    overlay["updated_at"] = _now()
    _write_overlay(overlay)
    return clean


def _provider_config_from_overlay(overlay_translation: dict, provider_id: str) -> dict:
    stored = {}
    providers = overlay_translation.get("providers")
    if isinstance(providers, dict) and isinstance(providers.get(provider_id), dict):
        stored = providers[provider_id]
    return merge_config(
        provider_id,
        env_layer(provider_id),
        legacy_layer(provider_id, overlay_translation),
        stored,
    )


def get_runtime() -> dict:
    feeds = read_json("feeds")
    settings = feeds.get("settings", {}) if isinstance(feeds, dict) else {}
    import translate

    values = translate.settings()
    providers = {
        provider_id: public_config(provider_id, values["providers"][provider_id])
        for provider_id in PROVIDER_IDS
    }
    translation = {
        "provider": values["provider"],
        "providers": providers,
        "provider_specs": public_specs(),
        # Legacy aliases kept for older clients.
        "libre_url": providers["libre"]["url"],
        "libre_key_set": providers["libre"]["key_set"],
        "ollama_url": providers["ollama"]["url"],
        "ollama_model": providers["ollama"]["model"],
    }
    return {"feeds": settings, "translation": translation, "ui": get_ui()}


def _validate_provider_field(provider_id: str, field: dict, value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    field_type = field.get("type")
    if field_type == "select":
        allowed = [str(option[0]) for option in field.get("options") or []]
        if allowed and text not in allowed:
            raise ConfigError(
                f"translation.providers.{provider_id}.{field['key']} must be one of {allowed}"
            )
    if field_type == "url" and text and not text.startswith(("http://", "https://")):
        raise ConfigError(
            f"translation.providers.{provider_id}.{field['key']} must start with http:// or https://"
        )
    return text


def save_runtime(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ConfigError("runtime: expected an object")
    translation = payload.get("translation", payload)
    if not isinstance(translation, dict):
        raise ConfigError("runtime.translation must be an object")

    overlay = copy.deepcopy(_read_overlay())
    current = overlay.setdefault("runtime", {}).setdefault("translation", {})
    if not isinstance(current, dict):
        current = {}
        overlay["runtime"]["translation"] = current

    if "provider" in translation:
        provider = str(translation["provider"] or "auto").lower()
        if provider not in ("auto", *PROVIDER_IDS):
            raise ConfigError(f"translation.provider must be auto/{'/'.join(PROVIDER_IDS)}")
        current["provider"] = provider
    for key in ("local_first", "fallback", "free_only", "auto_paid"):
        current.pop(key, None)

    current_providers = current.get("providers")
    if not isinstance(current_providers, dict):
        current_providers = {}
        current["providers"] = current_providers

    legacy = {
        "libre_url": ("libre", "url"),
        "libre_key": ("libre", "key"),
        "ollama_url": ("ollama", "url"),
        "ollama_model": ("ollama", "model"),
    }
    # Preserve values from the pre-provider schema before removing the old keys.
    for old_key, (provider_id, field_key) in legacy.items():
        if old_key not in current or old_key in translation:
            continue
        value = current[old_key]
        saved = current_providers.setdefault(provider_id, {})
        if not isinstance(saved, dict):
            saved = {}
            current_providers[provider_id] = saved
        if field_key in SECRET_KEYS[provider_id]:
            if value not in (None, ""):
                saved[field_key] = str(value).strip()
        elif value is not None:
            saved[field_key] = str(value).strip()

    clear_keys = translation.get("clear_keys") or []
    if not isinstance(clear_keys, list):
        raise ConfigError("translation.clear_keys must be a list")
    for provider_id in clear_keys:
        if provider_id not in PROVIDER_SPECS:
            raise ConfigError(f"Unknown translation provider: {provider_id}")
        saved = current_providers.get(provider_id)
        if isinstance(saved, dict):
            for secret_key in SECRET_KEYS[provider_id]:
                saved.pop(secret_key, None)

    incoming = translation.get("providers")
    if incoming is not None and not isinstance(incoming, dict):
        raise ConfigError("translation.providers must be an object")
    for provider_id, raw in (incoming or {}).items():
        if provider_id not in PROVIDER_SPECS:
            raise ConfigError(f"Unknown translation provider: {provider_id}")
        if not isinstance(raw, dict):
            raise ConfigError(f"translation.providers.{provider_id} must be an object")
        saved = current_providers.get(provider_id)
        if not isinstance(saved, dict):
            saved = {}
            current_providers[provider_id] = saved
        for field in PROVIDER_SPECS[provider_id]["fields"]:
            key = field["key"]
            if key not in raw:
                continue
            value = raw[key]
            if field.get("secret"):
                if value in (None, ""):
                    continue
                saved[key] = str(value).strip()
                continue
            clean = _validate_provider_field(provider_id, field, value)
            if clean is None:
                continue
            saved[key] = clean

    # Accept the old flat fields so existing overlays/bookmarks keep working.
    for old_key, (provider_id, field_key) in legacy.items():
        if old_key not in translation:
            continue
        value = translation[old_key]
        saved = current_providers.setdefault(provider_id, {})
        if not isinstance(saved, dict):
            saved = {}
            current_providers[provider_id] = saved
        if field_key in SECRET_KEYS[provider_id]:
            if value in (None, ""):
                saved.pop(field_key, None)
            else:
                saved[field_key] = str(value).strip()
            continue
        saved[field_key] = str(value or "").strip()
    for old_key in legacy:
        current.pop(old_key, None)

    provider = str(current.get("provider") or "auto").lower()
    current["provider"] = provider
    if provider in PROVIDER_SPECS:
        cfg = _provider_config_from_overlay(current, provider)
        if not is_ready(provider, cfg):
            missing = [
                field["label"]
                for field in PROVIDER_SPECS[provider]["fields"]
                if field.get("required") and not str(cfg.get(field["key"]) or "").strip()
            ]
            raise ConfigError(
                f"接口 {PROVIDER_SPECS[provider]['label']} 缺少必填项：{', '.join(missing)}"
            )

    overlay["updated_at"] = _now()
    _write_overlay(overlay)
    return get_runtime()


def export_bundle(include_secrets: bool = False) -> dict:
    overlay = _read_overlay()
    runtime = copy.deepcopy(overlay.get("runtime") or {})
    translation = runtime.get("translation") if isinstance(runtime, dict) else None
    if isinstance(translation, dict) and not include_secrets:
        runtime["translation"] = strip_secrets(translation)
    return {
        "format": "global-news-timeline-customization",
        "version": 1,
        "exported_at": _now(),
        "configs": copy.deepcopy(overlay.get("configs") or {}),
        "ui": get_ui(),
        "runtime": runtime,
    }


def import_bundle(bundle: dict, merge: bool = True) -> dict:
    if not isinstance(bundle, dict):
        raise ConfigError("bundle: expected an object")
    if bundle.get("format") not in (None, "global-news-timeline-customization"):
        raise ConfigError("bundle: unsupported format")
    configs = bundle.get("configs") or {}
    if not isinstance(configs, dict):
        raise ConfigError("bundle.configs must be an object")
    for name, data in configs.items():
        _check_name(name)
        _validate(name, data)
    ui = bundle.get("ui")
    clean_ui = _validate_ui(ui) if ui is not None else None
    runtime = bundle.get("runtime")
    if runtime is not None and not isinstance(runtime, dict):
        raise ConfigError("bundle.runtime must be an object")

    overlay = copy.deepcopy(_read_overlay()) if merge else {}
    overlay.setdefault("format", "global-news-timeline-customization")
    overlay.setdefault("version", 1)
    target = overlay.setdefault("configs", {})
    if not merge:
        target.clear()
    target.update(copy.deepcopy(configs))
    if clean_ui is not None:
        overlay["ui"] = clean_ui
    if isinstance(runtime, dict):
        overlay.setdefault("runtime", {}).update(copy.deepcopy(runtime))
    overlay["updated_at"] = _now()
    _write_overlay(overlay)
    reset_runtime_caches()
    return {"configs": sorted(configs), "ui": clean_ui is not None}


def reset_all() -> None:
    try:
        PATH.unlink()
    except FileNotFoundError:
        pass
    reset_runtime_caches()


def reset_runtime_caches() -> None:
    """Clear module-level caches so the next request sees new config."""
    try:
        import quality

        quality._cache = None
    except Exception:
        pass
    try:
        import contenttype

        contenttype._cache = None
    except Exception:
        pass
    try:
        import query_expand

        query_expand._CJK_VOCAB = None
        query_expand._ALIAS_INDEX = None
    except Exception:
        pass
    try:
        import eventgraph

        eventgraph._cache = None
    except Exception:
        pass
    try:
        import elections

        if hasattr(elections, "_CACHE"):
            elections._CACHE["mtime"] = None
            elections._CACHE["data"] = None
    except Exception:
        pass
