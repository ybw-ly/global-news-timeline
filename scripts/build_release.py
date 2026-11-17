#!/usr/bin/env python3
"""Build a distributable zip for GitHub Releases.

The archive contains the runnable project (server, web, config, deploy) but
leaves out the local database, logs, caches, temporary files and .git.
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

EXCLUDED_DIRS = {
    ".git",
    ".github",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}
EXCLUDED_PREFIXES = ("tmp_", ".chrome-", ".edge-", "backup")
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".log", ".pid", ".out")


def version() -> str:
    match = re.search(
        r'^VERSION\s*=\s*"([^"]+)"',
        (ROOT / "server" / "app.py").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return match.group(1) if match else "0.0.0"


def included(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = rel.parts
    if any(part in EXCLUDED_DIRS for part in parts):
        return False
    if any(part.startswith(EXCLUDED_PREFIXES) for part in parts):
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False

    if rel.parts[0] == "data":
        name = rel.name
        if name.startswith("news.db"):
            return False
        if rel.suffix in (".json", ".md", ".txt", ".csv", ".pid", ".out"):
            return False
        if rel.suffix.startswith(".db"):
            return False
        if len(rel.parts) > 1 and rel.parts[1] in ("raw", "backup"):
            return False

    return path.is_file()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    ver = version()
    DIST.mkdir(exist_ok=True)
    target = DIST / f"global-news-timeline-v{ver}.zip"

    files = sorted(
        path for path in ROOT.rglob("*") if included(path)
    )
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            arcname = Path("global-news-timeline") / path.relative_to(ROOT)
            archive.write(path, arcname.as_posix())

    checksum = sha256(target)
    checksum_file = DIST / "SHA256SUMS.txt"
    checksum_file.write_text(
        f"{checksum}  {target.name}\n", encoding="utf-8"
    )
    print(f"Built {target} ({target.stat().st_size / 1024 / 1024:.2f} MiB, {len(files)} files)")
    print(f"SHA256 {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
