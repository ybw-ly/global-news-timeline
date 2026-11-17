"""Shared controlled vocabularies: regions, languages, categories, countries."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import customization

ROOT = Path(__file__).resolve().parent.parent
COUNTRIES: dict[str, dict] = customization.read_json("countries")

REGIONS: dict[str, str] = {
    "north_america": "北美",
    "latin_america": "拉美",
    "europe": "欧洲",
    "middle_east": "中东",
    "africa": "非洲",
    "south_asia": "南亚",
    "east_asia": "东亚",
    "southeast_asia": "东南亚",
    "central_asia": "中亚",
    "oceania": "大洋洲",
    "other": "其他",
}

LANGUAGES: dict[str, str] = {
    "en": "英语",
    "zh": "中文",
    "zh-Hant": "中文（繁体）",
    "ja": "日语",
    "ko": "韩语",
    "ru": "俄语",
    "es": "西班牙语",
    "fr": "法语",
    "de": "德语",
    "ar": "阿拉伯语",
    "pt": "葡萄牙语",
    "tr": "土耳其语",
    "hi": "印地语",
    "id": "印尼语",
    "vi": "越南语",
    "th": "泰语",
    "it": "意大利语",
    "fa": "波斯语",
    "he": "希伯来语",
    "uk": "乌克兰语",
}

CATEGORIES: dict[str, str] = {
    "economy": "经济",
    "politics": "政治",
    "military": "军事",
    "other": "其他",
}

CATEGORY_ORDER = ["economy", "politics", "military", "other"]

CONTENT_TYPES: dict[str, str] = {
    "hard": "硬新闻",
    "analysis": "分析",
    "opinion": "评论",
}

OWNERSHIP: dict[str, str] = {
    "state": "国营",
    "state_funded": "国有资金",
    "public": "公共",
    "private": "私营",
    "aggregator": "聚合",
    "market": "预测市场",
}

# Language used for lexicon lookup (script variants share a base language).
LANGUAGE_BASE = {
    "zh-Hant": "zh",
    "pt-BR": "pt",
    "en-US": "en",
    "en-GB": "en",
}


def base_language(code: str | None) -> str:
    if not code:
        return "en"
    code = code.strip()
    return LANGUAGE_BASE.get(code, code.split("-")[0].lower())


def region_of(country: str | None) -> str:
    if not country:
        return "other"
    return COUNTRIES.get(country.upper(), {}).get("region", "other")


def region_label(code: str) -> str:
    return REGIONS.get(code, REGIONS["other"])


def language_label(code: str) -> str:
    return LANGUAGES.get(code, code or "未知")


def category_label(code: str) -> str:
    return CATEGORIES.get(code, CATEGORIES["other"])


def content_type_label(code: str | None) -> str:
    return CONTENT_TYPES.get(code or "hard", CONTENT_TYPES["hard"])


def ownership_label(code: str | None) -> str:
    return OWNERSHIP.get(code or "", "")


def country_label(code: str | None) -> str:
    if not code:
        return "未知"
    info = COUNTRIES.get(code.upper())
    return info["name_zh"] if info else code.upper()


PUBLISHER_DOMAINS = [
    ("timesofindia.indiatimes.com", "IN"), ("channelnewsasia.com", "SG"),
    ("middleeasteye.net", "GB"), ("washingtonpost.com", "US"),
    ("timesofisrael.com", "IL"), ("defensenews.com", "US"), ("defenseone.com", "US"),
    ("warontherocks.com", "US"), ("japantimes.co.jp", "JP"),
    ("folha.uol.com.br", "BR"), ("africanews.com", "CG"), ("allafrica.com", "ZA"),
    ("bangkokpost.com", "TH"), ("straitstimes.com", "SG"), ("politico.eu", "BE"),
    ("aljazeera.com", "QA"), ("aljazeera.net", "QA"), ("france24.com", "FR"),
    ("tehrantimes.com", "IR"), ("nikkei.asia", "JP"), ("asia.nikkei.com", "JP"),
    ("theguardian.com", "GB"), ("economist.com", "GB"), ("nytimes.com", "US"),
    ("scmp.com", "HK"), ("jpost.com", "IL"), ("haaretz.com", "IL"),
    ("kommersant.ru", "RU"), ("tass.com", "RU"), ("cgtn.com", "CN"),
    ("xinhuanet.com", "CN"), ("globaltimes.cn", "CN"), ("mehrnews.com", "IR"),
    ("irna.ir", "IR"), ("elpais.com", "ES"), ("lemonde.fr", "FR"),
    ("lefigaro.fr", "FR"), ("spiegel.de", "DE"), ("zeit.de", "DE"),
    ("corriere.it", "IT"), ("ansa.it", "IT"), ("cnbc.com", "US"),
    ("reuters.com", "GB"), ("apnews.com", "US"), ("npr.org", "US"),
    ("bbc.com", "GB"), ("bbc.co.uk", "GB"), ("cnn.com", "US"),
    ("ft.com", "GB"), ("dw.com", "DE"), ("cbc.ca", "CA"),
    ("abc.net.au", "AU"), ("yonhapnews.co.kr", "KR"), ("yna.co.kr", "KR"),
    ("un.org", "US"), ("al-monitor.com", "US"),
]
PUBLISHER_DOMAINS.sort(key=lambda item: len(item[0]), reverse=True)

COUNTRY_TLD = [
    (".com.cn", "CN"), (".co.jp", "JP"), (".co.kr", "KR"), (".com.hk", "HK"),
    (".com.tw", "TW"), (".com.sg", "SG"), (".co.in", "IN"), (".co.uk", "GB"),
    (".co.za", "ZA"), (".com.au", "AU"), (".co.nz", "NZ"), (".com.br", "BR"),
    (".com.mx", "MX"), (".com.ar", "AR"), (".com.tr", "TR"),
    (".jp", "JP"), (".kr", "KR"), (".cn", "CN"), (".hk", "HK"), (".tw", "TW"),
    (".sg", "SG"), (".in", "IN"), (".ru", "RU"), (".ua", "UA"), (".de", "DE"),
    (".fr", "FR"), (".es", "ES"), (".it", "IT"), (".br", "BR"), (".mx", "MX"),
    (".ar", "AR"), (".tr", "TR"), (".il", "IL"), (".ir", "IR"), (".sa", "SA"),
    (".ae", "AE"), (".qa", "QA"), (".eg", "EG"), (".za", "ZA"), (".au", "AU"),
    (".nz", "NZ"), (".uk", "GB"), (".ca", "CA"), (".us", "US"), (".ch", "CH"),
    (".nl", "NL"), (".be", "BE"), (".se", "SE"), (".no", "NO"), (".dk", "DK"),
    (".fi", "FI"), (".pl", "PL"), (".gr", "GR"), (".pt", "PT"), (".ie", "IE"),
    (".at", "AT"), (".cz", "CZ"), (".ro", "RO"), (".hu", "HU"),
]


def country_from_url(url: str | None, fallback: str | None = None) -> str | None:
    if not url:
        return fallback
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return fallback
    for domain, code in PUBLISHER_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return code
    for suffix, code in COUNTRY_TLD:
        if host.endswith(suffix):
            return code
    return fallback


_STOPWORDS = {
    "en": {"the", "and", "of", "to", "in", "for", "with", "says", "after", "on", "at", "by", "from", "as", "is", "are", "was", "were", "a", "an", "that", "this", "its", "his", "her", "their"},
    "es": {"el", "la", "los", "las", "de", "que", "en", "por", "para", "con", "un", "una", "del", "al", "se", "su", "tras", "sobre", "como", "más"},
    "fr": {"le", "la", "les", "des", "du", "et", "en", "pour", "avec", "sur", "un", "une", "dans", "au", "aux", "est", "sont", "après", "selon"},
    "de": {"der", "die", "das", "und", "von", "mit", "für", "auf", "ist", "sind", "im", "in", "zu", "den", "dem", "ein", "eine", "nach", "bei"},
    "pt": {"o", "a", "os", "as", "de", "que", "em", "para", "com", "não", "um", "uma", "do", "da", "dos", "das", "no", "na", "sobre", "após"},
    "it": {"il", "la", "i", "gli", "di", "che", "per", "con", "non", "un", "una", "del", "della", "in", "su", "dopo", "secondo"},
    "tr": {"ve", "bir", "bu", "için", "ile", "olan", "da", "de", "ne", "sonra", "göre", "daha"},
    "id": {"yang", "dan", "di", "ke", "dari", "untuk", "dengan", "ini", "itu", "pada", "sebagai", "akan"},
    "vi": {"và", "của", "những", "các", "trong", "với", "một", "để", "khi", "sau", "theo"},
}


_SCRIPT_PATTERNS = {
    "zh": re.compile(r"[㐀-鿿]"),
    "zh-Hant": re.compile(r"[㐀-鿿]"),
    "ja": re.compile(r"[぀-ヿ]"),
    "ko": re.compile(r"[가-힯]"),
    "ru": re.compile(r"[Ѐ-ӿ]"),
    "uk": re.compile(r"[Ѐ-ӿ]"),
    "ar": re.compile(r"[؀-ۿ]"),
    "fa": re.compile(r"[؀-ۿ]"),
    "he": re.compile(r"[֐-׿]"),
    "hi": re.compile(r"[ऀ-ॿ]"),
    "th": re.compile(r"[฀-๿]"),
}
_LATIN = re.compile(r"[A-Za-zÀ-ÿ]")


def script_matches(text: str, language: str) -> bool:
    """Cheap sanity check used for aggregator feeds whose edition language
    can be silently ignored by the provider (e.g. an English fallback feed)."""
    text = text or ""
    if language in _SCRIPT_PATTERNS:
        return bool(_SCRIPT_PATTERNS[language].search(text))
    if language == "en":
        letters = _LATIN.findall(text)
        total = [c for c in text if c.isalpha()]
        return bool(letters) and len(letters) / max(len(total), 1) >= 0.6
    return True


def detect_language(text: str, hint: str | None = None) -> str:
    if hint:
        return hint
    if re.search(r"[぀-ヿ]", text):
        return "ja"
    if re.search(r"[가-힯]", text):
        return "ko"
    if re.search(r"[؀-ۿ]", text):
        if re.search(r"[پچژگ]", text):
            return "fa"
        return "ar"
    if re.search(r"[֐-׿]", text):
        return "he"
    if re.search(r"[ऀ-ॿ]", text):
        return "hi"
    if re.search(r"[฀-๿]", text):
        return "th"
    if re.search(r"[Ѐ-ӿ]", text):
        if re.search(r"[іїєґІЇЄҐ]", text):
            return "uk"
        return "ru"
    if re.search(r"[一-鿿]", text):
        return "zh"

    words = re.findall(r"[a-zA-ZÀ-ÿа-яА-Я]+", text.lower())
    if not words:
        return "en"
    counts = {lang: sum(1 for w in words if w in stop) for lang, stop in _STOPWORDS.items()}
    best = max(counts, key=counts.get)
    return best if counts[best] >= 2 else "en"
