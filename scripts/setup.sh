#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-/tmp/md-advisor-pip-cache}"
python3 -c 'import sys; assert sys.version_info[:2] == (3,12), "Python 3.12 required"'
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pip check
