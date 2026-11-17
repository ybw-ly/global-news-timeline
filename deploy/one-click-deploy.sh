#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1; then
    PY=python
  else
    echo "Python 3.10+ was not found on PATH." >&2
    exit 1
  fi
fi

if ! "$PY" - <<'PYCHECK'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PYCHECK
then
  echo "Python 3.10+ is required." >&2
  exit 1
fi

URL="http://127.0.0.1:${PORT:-8765}"
echo "Starting Global News Timeline on $URL ..."

"$PY" server/app.py &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT INT TERM

sleep 2
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
  open "$URL" >/dev/null 2>&1 || true
fi

wait "$SERVER_PID"
