#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

WHEELHOUSE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wheelhouse) WHEELHOUSE="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -d .venv ]]; then
  python3 -m venv --system-site-packages .venv
fi

if [[ -n "$WHEELHOUSE" ]]; then
  .venv/bin/python -m pip install --no-index --find-links "$WHEELHOUSE" \
    fastapi "uvicorn[standard]" python-multipart
else
  .venv/bin/python -m pip install --upgrade \
    fastapi "uvicorn[standard]" python-multipart
fi

.venv/bin/python - <<'PY'
import importlib.util
for name in ["fastapi", "uvicorn", "multipart", "torch", "ultralytics"]:
    print(name, bool(importlib.util.find_spec(name)))
PY
