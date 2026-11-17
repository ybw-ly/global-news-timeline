"""Live adapter for Brazil's 2026 presidential runoff.

The TSE publishes the official count as static JSON files.  This module keeps a
very small in-memory cache so the browser can poll the local server instead of
hammering the electoral court.  The URL layout is documented by the TSE:

    https://resultados.tse.jus.br/oficial/ele2026/6258/dados/br/br-c0001-e006258-u.json

Election 6258 is the 2026 federal runoff; office 0001 is President.  State
files use the same name with the UF in both the folder and the prefix.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request

TSE_ROOT = "https://resultados.tse.jus.br/oficial/ele2026/6258/dados"
TSE_FILE_SUFFIX = "c0001-e006258-u.json"
CACHE_TTL = 8.0

_UFS = {
    "ac", "al", "ap", "am", "ba", "ce", "df", "es", "go", "ma", "mt", "ms",
    "mg", "pa", "pb", "pr", "pe", "pi", "rj", "rn", "rs", "ro", "rr", "sc",
    "sp", "se", "to",
}
_SCOPES = {"br"} | _UFS
_CACHE: dict[str, tuple[float, dict]] = {}
_LOCK = threading.Lock()
_SCOPE_RE = re.compile(r"^(br|[a-z]{2})$")


class BrazilResultError(RuntimeError):
    pass


def _as_int(value) -> int:
    try:
        return int(str(value).replace(".", "").strip())
    except (TypeError, ValueError):
        return 0


def _as_float(value) -> float:
    try:
        return float(str(value).replace(".", "").replace(",", ".").strip())
    except (TypeError, ValueError):
        return 0.0


def _normalise(payload: dict, scope: str) -> dict:
    carg = (payload.get("carg") or [{}])[0]
    candidates: list[dict] = []
    for coalition in carg.get("agr") or []:
        for party in coalition.get("par") or []:
            for candidate in party.get("cand") or []:
                candidates.append(
                    {
                        "name": candidate.get("nmu") or candidate.get("nm") or "",
                        "full_name": candidate.get("nm") or "",
                        "party": party.get("sg") or "",
                        "number": str(candidate.get("n") or ""),
                        "votes": _as_int(candidate.get("vap")),
                        "pct": _as_float(candidate.get("pvap")),
                        "status": candidate.get("st") or "",
                    }
                )
    candidates.sort(key=lambda item: (-item["votes"], item["name"]))

    sections = payload.get("s") or {}
    electorate = payload.get("e") or {}
    votes = payload.get("v") or {}
    generated = " ".join(
        part for part in (payload.get("dg") or "", payload.get("hg") or "") if part
    ).strip()

    return {
        "ok": True,
        "scope": scope,
        "generated_at": generated,
        "finished": payload.get("and") == "f",
        "counted_sections": _as_int(sections.get("st")),
        "total_sections": _as_int(sections.get("ts")),
        "counted_pct": _as_float(sections.get("pst")),
        "counted_electorate": _as_int(electorate.get("est")),
        "total_electorate": _as_int(electorate.get("te")),
        "valid_votes": _as_int(votes.get("tvn")),
        "total_votes": _as_int(votes.get("tv")),
        "blank_votes": _as_int(votes.get("vb")),
        "null_votes": _as_int(votes.get("vn")),
        "abstention": _as_int(electorate.get("a")),
        "abstention_pct": _as_float(electorate.get("pa")),
        "candidates": candidates,
        "source": "TSE / resultados.tse.jus.br",
    }


def _url(scope: str) -> str:
    return f"{TSE_ROOT}/{scope}/{scope}-{TSE_FILE_SUFFIX}"


def _download(scope: str) -> dict:
    request = urllib.request.Request(
        _url(scope),
        headers={
            "User-Agent": "GlobalNewsTimeline/1.0 (local OSINT tracker)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=9) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8-sig"))


def fetch_results(scope: str = "br") -> dict:
    """Return a compact, browser-friendly snapshot for one scope.

    ``scope`` is ``br`` or a two-letter Brazilian state code.  The last good
    snapshot is kept and returned with ``stale=true`` if the TSE is temporarily
    unreachable.
    """
    scope = (scope or "br").strip().lower()
    if not _SCOPE_RE.match(scope) or scope not in _SCOPES:
        return {"ok": False, "scope": scope, "error": "Unsupported scope"}

    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(scope)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]

    try:
        payload = _download(scope)
        data = _normalise(payload, scope)
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
    ) as exc:
        if cached:
            return {**cached[1], "stale": True, "error": str(exc)[:160]}
        return {
            "ok": False,
            "scope": scope,
            "error": str(exc)[:160],
            "source": "TSE / resultados.tse.jus.br",
        }

    with _LOCK:
        _CACHE[scope] = (now, data)
    return data
