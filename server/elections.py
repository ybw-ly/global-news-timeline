"""Election registry and live-result dispatcher.

Elections are declared in ``config/elections.json``.  Adding a new election is
a config-only change; live result feeds are plugged in through ``adapter``.
Only the Brazilian TSE adapter is implemented today.  Other elections still
get the timeline / watchlist / sources view and can be extended without
touching the front-end.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import brazil

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "elections.json"

_LOCK = threading.Lock()
_CACHE: dict = {"mtime": None, "data": None}


def _load() -> dict:
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        return {"version": 1, "default": "auto", "elections": []}

    with _LOCK:
        if _CACHE["mtime"] == mtime and _CACHE["data"] is not None:
            return _CACHE["data"]

    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("elections"), list):
        raise ValueError("config/elections.json must contain an elections list")

    with _LOCK:
        _CACHE["mtime"] = mtime
        _CACHE["data"] = data
    return data


def _summary(item: dict) -> dict:
    adapter = item.get("adapter") or {}
    return {
        "id": item.get("id", ""),
        "country_code": item.get("country_code", ""),
        "country": item.get("country", ""),
        "name_zh": item.get("name_zh", ""),
        "name_en": item.get("name_en", ""),
        "round_zh": item.get("round_zh", ""),
        "status": item.get("status", ""),
        "election_date": item.get("election_date", ""),
        "timezone": item.get("timezone", ""),
        "timezone_label": item.get("timezone_label", ""),
        "official_url": item.get("official_url", ""),
        "adapter": adapter.get("type", "none"),
    }


def list_elections() -> list[dict]:
    return [_summary(item) for item in _load()["elections"] if item.get("id")]


def get_election(election_id: str) -> dict | None:
    election_id = (election_id or "").strip()
    for item in _load()["elections"]:
        if item.get("id") == election_id:
            return item
    return None


def default_election() -> dict | None:
    data = _load()
    elections = [item for item in data["elections"] if item.get("id")]
    if not elections:
        return None

    preferred = data.get("default", "auto")
    if preferred and preferred != "auto":
        for item in elections:
            if item.get("id") == preferred:
                return _summary(item)

    live = [item for item in elections if item.get("status") == "live"]
    if live:
        return _summary(live[0])

    upcoming = sorted(
        (item for item in elections if item.get("status") == "upcoming"),
        key=lambda item: item.get("election_date", "9999-12-31"),
    )
    if upcoming:
        return _summary(upcoming[0])

    finished = sorted(
        (item for item in elections if item.get("status") == "finished"),
        key=lambda item: item.get("election_date", ""),
        reverse=True,
    )
    return _summary(finished[0]) if finished else _summary(elections[0])


def fetch_election_results(election_id: str, scope: str = "br") -> dict:
    election = get_election(election_id)
    if not election:
        return {"ok": False, "error": "Unknown election", "election": election_id}

    adapter = election.get("adapter") or {}
    kind = adapter.get("type", "none")

    if kind == "tse":
        return brazil.fetch_results(
            scope,
            root=adapter.get("root", brazil.TSE_ROOT),
            file_suffix=adapter.get("file_suffix", brazil.TSE_FILE_SUFFIX),
            allowed_scopes=adapter.get("scopes"),
        )

    return {
        "ok": False,
        "election": election_id,
        "adapter": kind,
        "error": "该选举暂未接入实时计票数据源",
        "official_url": election.get("official_url", ""),
        "official_label": election.get("official_label", ""),
    }
