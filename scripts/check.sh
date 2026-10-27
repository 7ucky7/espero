#!/usr/bin/env bash
# Run the same job as .github/workflows/ci.yml, locally.
#
#   ./scripts/check.sh --install   # first run: create/refresh the editable install
#   ./scripts/check.sh             # tests + the audit table + CLI smoke test
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -n "${PYTHON:-}" ]; then
    PY=$PYTHON
elif [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
else
    PY=python3
fi

if [ "${1:-}" = "--install" ]; then
    echo "== install =="
    "$PY" -m pip install -e ".[chart]"
fi

echo "== tests =="
"$PY" -m unittest discover -s tests -v

echo
echo "== audit table =="
"$PY" -m espero matrix

echo
echo "== cli =="
"$PY" -m espero --version
"$PY" -m espero backtest --fee-bps 60 | tail -3

echo
echo "ok"
