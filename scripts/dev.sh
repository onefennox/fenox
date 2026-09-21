#!/usr/bin/env bash
# Run the Fenox hub from a source checkout with reload enabled.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e ".[dev]"

exec .venv/bin/fenox serve --no-browser --reload "$@"
