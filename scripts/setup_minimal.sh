#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CREATE_VENV=1
INSTALL_YOLO=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-venv) CREATE_VENV=0; shift ;;
    --install-yolo) INSTALL_YOLO=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

echo "project_dir=$ROOT_DIR"
echo "python=$(command -v python3)"
python3 --version

if [[ "$CREATE_VENV" -eq 1 ]]; then
  if [[ ! -d .venv ]]; then
    python3 -m venv --system-site-packages .venv
  fi
  # shellcheck disable=SC1091
  . .venv/bin/activate
fi

python - <<'PY'
import importlib
for name in ["numpy", "cv2", "torch", "yaml", "psutil", "ultralytics"]:
    try:
        mod = importlib.import_module(name)
        print(f"{name}: ok {getattr(mod, '__version__', 'unknown')}")
    except Exception as exc:
        print(f"{name}: missing_or_error {type(exc).__name__}: {exc}")
PY

if [[ "$INSTALL_YOLO" -eq 1 ]]; then
  echo "installing project-local Python packages"
  python -m pip install --upgrade pip
  python -m pip install psutil pyyaml ultralytics
fi

echo "setup_minimal complete"

