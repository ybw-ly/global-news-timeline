"""Metadata for the built-in translation providers.

The GUI renders provider-specific fields from these definitions, and the server
uses the same definitions to validate, mask and export configuration.  No secret
values live in this module: API keys are written to ``data/customization.json``
by the customization overlay.
"""
from __future__ import annotations

import copy
import os
import re

PROVIDER_ORDER = (
    "libre",
    "ollama",
    "mymemory",
    "deepl",
    "google",
    "azure",
    "openai",
    "baidu",
    "youdao",
    "custom",
)

PROVIDER_SPECS: dict[str, dict] = {
    "libre": {
        "label": "LibreTranslate",
        "kind": "free",
        "help": "自建或托管的 LibreTranslate。localhost/私网地址在“仅免费”模式下也可用。",
        "fields": [
            {
                "key": "url", "label": "服务地址", "type": "url", "required": True,
                "env": "LIBRETRANSLATE_URL", "default": "",
                "placeholder": "http://127.0.0.1:5000", "full": True,
            },
            {
                "key": "key", "label": "API Key", "type": "password", "secret": True,
                "env": "LIBRETRANSLATE_API_KEY", "default": "",
                "placeholder": "可选；留空表示无密钥",
            },
        ],
    },
    "ollama": {
        "label": "本地 Ollama",
        "kind": "local",
        "help": "本地大模型翻译，隐私最好但 8B 模型通常较慢；自动翻译会跳过它。",
        "fields": [
            {
                "key": "url", "label": "Ollama 地址", "type": "url", "required": True,
                "env": "OLLAMA_URL", "default": "http://127.0.0.1:11434",
                "placeholder": "http://127.0.0.1:11434", "full": True,
            },
            {
                "key": "model", "label": "模型", "type": "text", "required": True,
                "env": "OLLAMA_MODEL", "default": "qwen3-vl:8b",
                "placeholder": "qwen3-vl:8b",
            },
        ],
    },
    "mymemory": {
        "label": "MyMemory（免费）",
        "kind": "free",
        "help": "匿名免费接口，无需 Key；会把公开标题/摘要发到第三方，并有每日额度。",
        "fields": [
            {
                "key": "email", "label": "联系邮箱（可选）", "type": "email",
                "env": "MYMEMORY_EMAIL", "default": "",
                "placeholder": "you@example.com",
                "help": "提供邮箱可提高 MyMemory 免费额度；会随请求发给 MyMemory。",
            },
        ],
    },
    "deepl": {
        "label": "DeepL",
        "kind": "paid",
        "help": "DeepL API Free 的 Key 通常以 :fx 结尾；Pro Key 请把地址改成 api.deepl.com。",
        "fields": [
            {
                "key": "key", "label": "API Key", "type": "password", "secret": True,
                "required": True, "env": "DEEPL_API_KEY", "default": "",
                "placeholder": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx:fx",
            },
            {
                "key": "endpoint", "label": "接口地址", "type": "url",
                "env": "DEEPL_ENDPOINT", "default": "https://api-free.deepl.com/v2/translate",
                "placeholder": "https://api-free.deepl.com/v2/translate", "full": True,
            },
        ],
    },
    "google": {
        "label": "Google Cloud Translation",
        "kind": "paid",
        "help": "使用 Google Cloud Translation Basic v2 的 API Key（不是 OAuth 客户端）。",
        "fields": [
            {
                "key": "key", "label": "API Key", "type": "password", "secret": True,
                "required": True, "env": "GOOGLE_TRANSLATE_API_KEY", "default": "",
                "placeholder": "AIza...",
            },
            {
                "key": "endpoint", "label": "接口地址", "type": "url",
                "env": "GOOGLE_TRANSLATE_ENDPOINT",
                "default": "https://translation.googleapis.com/language/translate/v2",
                "placeholder": "https://translation.googleapis.com/language/translate/v2",
                "full": True,
            },
        ],
    },
    "azure": {
        "label": "Azure Translator",
        "kind": "paid",
        "help": "Azure AI Translator 的 Key、区域和资源地址；区域必填（例如 eastasia）。",
        "fields": [
            {
                "key": "key", "label": "API Key", "type": "password", "secret": True,
                "required": True, "env": "AZURE_TRANSLATOR_KEY", "default": "",
                "placeholder": "Azure Translator key",
            },
            {
                "key": "region", "label": "区域", "type": "text", "required": True,
                "env": "AZURE_TRANSLATOR_REGION", "default": "",
                "placeholder": "eastasia",
            },
            {
                "key": "endpoint", "label": "资源地址", "type": "url",
                "env": "AZURE_TRANSLATOR_ENDPOINT",
                "default": "https://api.cognitive.microsofttranslator.com",
                "placeholder": "https://api.cognitive.microsofttranslator.com",
                "full": True,
            },
        ],
    },
    "openai": {
        "label": "OpenAI 兼容接口",
        "kind": "paid",
        "help": "兼容 /v1/chat/completions 的服务：OpenAI、DeepSeek、Moonshot、Qwen、vLLM 等。",
        "presets": [
            {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
            {"label": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
            {"label": "Moonshot", "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
            {"label": "阿里云百炼 / Qwen", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
            {"label": "SiliconFlow", "base_url": "https://api.siliconflow.cn/v1", "model": "Qwen/Qwen2.5-7B-Instruct"},
            {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-4o-mini"},
        ],
        "fields": [
            {
                "key": "base_url", "label": "Base URL", "type": "url", "required": True,
                "env": "OPENAI_BASE_URL", "default": "https://api.openai.com/v1",
                "placeholder": "https://api.openai.com/v1", "full": True,
            },
            {
                "key": "key", "label": "API Key", "type": "password", "secret": True,
                "required": True, "env": "OPENAI_API_KEY", "default": "",
                "placeholder": "sk-...",
            },
            {
                "key": "model", "label": "模型", "type": "text", "required": True,
                "env": "OPENAI_MODEL", "default": "gpt-4o-mini",
                "placeholder": "gpt-4o-mini / deepseek-chat / qwen-plus",
            },
        ],
    },
    "baidu": {
        "label": "百度翻译",
        "kind": "paid",
        "help": "百度翻译开放平台的 APP ID 与密钥；使用 MD5 签名。",
        "fields": [
            {
                "key": "appid", "label": "APP ID", "type": "text", "required": True,
                "env": "BAIDU_TRANSLATE_APPID", "default": "",
                "placeholder": "2024...",
            },
            {
                "key": "key", "label": "密钥", "type": "password", "secret": True,
                "required": True, "env": "BAIDU_TRANSLATE_KEY", "default": "",
                "placeholder": "百度翻译密钥",
            },
            {
                "key": "endpoint", "label": "接口地址", "type": "url",
                "env": "BAIDU_TRANSLATE_ENDPOINT",
                "default": "https://fanyi-api.baidu.com/api/trans/vip/translate",
                "placeholder": "https://fanyi-api.baidu.com/api/trans/vip/translate",
                "full": True,
            },
        ],
    },
    "youdao": {
        "label": "有道智云翻译",
        "kind": "paid",
        "help": "有道智云翻译的 App Key 与 App Secret；使用 v3 SHA256 签名。",
        "fields": [
            {
                "key": "app_key", "label": "App Key", "type": "text", "required": True,
                "env": "YOUDAO_APP_KEY", "default": "", "placeholder": "有道 App Key",
            },
            {
                "key": "app_secret", "label": "App Secret", "type": "password", "secret": True,
                "required": True, "env": "YOUDAO_APP_SECRET", "default": "",
                "placeholder": "有道 App Secret",
            },
            {
                "key": "endpoint", "label": "接口地址", "type": "url",
                "env": "YOUDAO_ENDPOINT", "default": "https://openapi.youdao.com/api",
                "placeholder": "https://openapi.youdao.com/api", "full": True,
            },
        ],
    },
    "custom": {
        "label": "自定义 HTTP 接口",
        "kind": "custom",
        "help": "给没有内置适配器的翻译 API 用；请求体/响应路径都可自己写，支持 {{text}}、{{source}}、{{target}}、{{key}} 占位符。",
        "fields": [
            {
                "key": "url", "label": "接口地址", "type": "url", "required": True,
                "env": "CUSTOM_TRANSLATE_URL", "default": "",
                "placeholder": "https://api.example.com/translate", "full": True,
            },
            {
                "key": "key", "label": "API Key", "type": "password", "secret": True,
                "env": "CUSTOM_TRANSLATE_KEY", "default": "",
                "placeholder": "可选；可在请求头里用 {{key}}",
            },
            {
                "key": "method", "label": "方法", "type": "select", "default": "POST",
                "options": [["POST", "POST"], ["GET", "GET"]],
            },
            {
                "key": "headers", "label": "请求头 JSON", "type": "textarea", "full": True,
                "default": "", "placeholder": "{\"Authorization\": \"Bearer {{key}}\"}",
                "help": "可选；值里可用 {{key}}。",
            },
            {
                "key": "body", "label": "请求体 JSON 模板", "type": "textarea", "full": True,
                "default": "",
                "placeholder": "{\"text\": {{text}}, \"source\": {{source}}, \"target\": {{target}}}",
                "help": "POST 用；占位符会替换为 JSON 字符串。留空则发送 text/source/target。",
            },
            {
                "key": "result_path", "label": "响应路径", "type": "text", "default": "translation",
                "placeholder": "translation / data.translations.0.text",
                "help": "点号路径；数组用数字，例如 data.translations.0.text。",
            },
        ],
    },
}

PROVIDER_IDS = tuple(PROVIDER_ORDER)
FIELD_KEYS = {pid: {field["key"] for field in spec["fields"]} for pid, spec in PROVIDER_SPECS.items()}
SECRET_KEYS = {
    pid: {field["key"] for field in spec["fields"] if field.get("secret")}
    for pid, spec in PROVIDER_SPECS.items()
}
URL_KEYS = {"url", "endpoint", "base_url"}

_LEGACY_KEYS = {
    "libre": {"url": "libre_url", "key": "libre_key"},
    "ollama": {"url": "ollama_url", "model": "ollama_model"},
}


def defaults(provider_id: str) -> dict:
    return {
        field["key"]: copy.deepcopy(field.get("default", ""))
        for field in PROVIDER_SPECS[provider_id]["fields"]
    }


def env_layer(provider_id: str) -> dict:
    layer = {}
    for field in PROVIDER_SPECS[provider_id]["fields"]:
        env = field.get("env")
        if env and os.environ.get(env) is not None:
            layer[field["key"]] = os.environ[env]
    return layer


def legacy_layer(provider_id: str, data: dict) -> dict:
    mapping = _LEGACY_KEYS.get(provider_id) or {}
    layer = {}
    for key, old_key in mapping.items():
        if old_key in data and data[old_key] is not None:
            layer[key] = data[old_key]
    return layer


def merge_config(provider_id: str, *layers: dict | None) -> dict:
    cfg = defaults(provider_id)
    allowed = FIELD_KEYS[provider_id]
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        for key, value in layer.items():
            if key in allowed and value is not None:
                cfg[key] = str(value)
    for key in URL_KEYS:
        if cfg.get(key):
            cfg[key] = cfg[key].rstrip("/")
    return cfg


def is_ready(provider_id: str, cfg: dict) -> bool:
    for field in PROVIDER_SPECS[provider_id]["fields"]:
        if field.get("required") and not str(cfg.get(field["key"]) or "").strip():
            return False
    return True


def is_paid(provider_id: str) -> bool:
    return PROVIDER_SPECS.get(provider_id, {}).get("kind") == "paid"


def public_specs() -> list[dict]:
    specs = []
    for provider_id in PROVIDER_ORDER:
        spec = copy.deepcopy(PROVIDER_SPECS[provider_id])
        spec["id"] = provider_id
        for field in spec["fields"]:
            field.pop("env", None)
        specs.append(spec)
    return specs


def public_config(provider_id: str, cfg: dict) -> dict:
    out = {}
    for field in PROVIDER_SPECS[provider_id]["fields"]:
        key = field["key"]
        if field.get("secret"):
            out[f"{key}_set"] = bool(str(cfg.get(key) or "").strip())
        else:
            out[key] = cfg.get(key, field.get("default", ""))
    out["ready"] = is_ready(provider_id, cfg)
    return out


def strip_secrets(translation: dict) -> dict:
    """Return a copy with every provider secret removed (used by export)."""
    clean = copy.deepcopy(translation or {})
    providers = clean.get("providers")
    if isinstance(providers, dict):
        for provider_id, cfg in providers.items():
            if not isinstance(cfg, dict):
                continue
            for key in SECRET_KEYS.get(provider_id, set()):
                cfg.pop(key, None)
    for key in ("libre_key",):
        clean.pop(key, None)
    return clean


def detect_key_hints(key: str) -> list[dict]:
    """Best-effort, offline provider hints for a pasted API key.

    A key alone often cannot identify a provider (many OpenAI-compatible
    services use the same ``sk-`` prefix), so hints carry a confidence level
    and only include fields that can be inferred safely.
    """
    key = (key or "").strip()
    if not key or len(key) > 512:
        return []

    hints: list[dict] = []
    seen: set[str] = set()

    def add(provider: str, confidence: str, note: str, target_field: str = "key", **fields):
        if provider not in PROVIDER_SPECS or provider in seen:
            return
        seen.add(provider)
        hints.append({
            "provider": provider,
            "confidence": confidence,
            "note": note,
            "target_field": target_field,
            "fields": fields,
        })

    if key.endswith(":fx"):
        add(
            "deepl", "high", "DeepL API Free Key",
            endpoint="https://api-free.deepl.com/v2/translate",
        )
    elif re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        key,
    ):
        add(
            "deepl", "medium", "格式像 DeepL API Pro Key",
            endpoint="https://api.deepl.com/v2/translate",
        )

    if key.startswith("AIza"):
        add(
            "google", "high", "Google API Key",
            endpoint="https://translation.googleapis.com/language/translate/v2",
        )

    if key.startswith("sk-or-v1-"):
        add(
            "openai", "high", "OpenRouter Key",
            base_url="https://openrouter.ai/api/v1",
            model="openai/gpt-4o-mini",
            preset="OpenRouter",
        )
    elif key.startswith("sk-ant-"):
        add("custom", "low", "Anthropic Key；当前没有内置 Anthropic 适配器，可用自定义 HTTP")
    elif key.startswith("sk-"):
        add(
            "openai", "medium",
            "sk- 前缀常见于 OpenAI/DeepSeek/Moonshot/Qwen 等兼容接口；请确认预设",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
            preset="OpenAI",
        )

    if re.fullmatch(r"\d{8,20}", key):
        add("baidu", "medium", "格式像百度翻译 APP ID；还需要填密钥", target_field="appid")

    if re.fullmatch(r"[0-9a-fA-F]{16}", key) and re.search(r"[a-fA-F]", key):
        add("youdao", "medium", "格式像有道 App Key；还需要填 App Secret", target_field="app_key")

    if re.fullmatch(r"[0-9a-fA-F]{32}", key):
        add("azure", "low", "32 位十六进制，可能是 Azure Translator Key，还需要区域")
        add("baidu", "low", "也可能是百度翻译密钥")
        add("youdao", "low", "也可能是有道 App Secret")

    return hints[:5]
