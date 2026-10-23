#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
exec "${PYTHON:-python3}" server/app.py
