#!/usr/bin/env python3
"""Run one ingestion cycle and exit.

Useful for an external scheduler (cron, systemd timer, NAS task) when you do
not want the web process to keep a background scheduler alive.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from ingest import refresh  # noqa: E402


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    result = refresh(force=True)
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
