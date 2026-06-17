#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CUSPARSELT_VERSION="${CUSPARSELT_VERSION:-0.6.2.3}"
TORCH_WHEEL_URL="${TORCH_WHEEL_URL:-https://developer.download.nvidia.com/compute/redist/jp/v61/pytorch/torch-2.5.0a0+872d972e41.nv24.08.17622132-cp310-cp310-linux_aarch64.whl}"
CACHE_DIR="${CACHE_DIR:-$ROOT_DIR/.cache}"

mkdir -p "$CACHE_DIR/cusparselt" "$CACHE_DIR/wheels"

if [[ ! -d .venv ]]; then
  python3 -m venv --system-site-packages .venv
fi

install_cusparselt() {
  if ldconfig -p 2>/dev/null | grep -q 'libcusparseLt.so.0'; then
    echo "cuSPARSELt already present"
    return
  fi
  local name="libcusparse_lt-linux-aarch64-${CUSPARSELT_VERSION}-archive"
  local url="https://developer.download.nvidia.com/compute/cusparselt/redist/libcusparse_lt/linux-aarch64/${name}.tar.xz"
  cd "$CACHE_DIR/cusparselt"
  if [[ ! -f "${name}.tar.xz" ]]; then
    curl --fail --location --retry 3 -o "${name}.tar.xz" "$url"
  fi
  rm -rf "$name"
  tar -xf "${name}.tar.xz"
  sudo cp -a "${name}/include/"* /usr/local/cuda/include/
  sudo cp -a "${name}/lib/"* /usr/local/cuda/lib64/
  sudo ldconfig
  cd "$ROOT_DIR"
}

install_torch() {
  local wheel="$CACHE_DIR/wheels/$(basename "$TORCH_WHEEL_URL")"
  if [[ ! -f "$wheel" ]]; then
    curl --fail --location --retry 3 -o "$wheel" "$TORCH_WHEEL_URL"
  fi
  .venv/bin/python -m pip uninstall -y torch || true
  .venv/bin/python -m pip install --no-cache-dir "$wheel"
}

install_cusparselt
install_torch

.venv/bin/python - <<'PY'
import torch
print("torch_version", torch.__version__)
print("cuda_available", torch.cuda.is_available())
print("cuda_version", torch.version.cuda)
print("device_count", torch.cuda.device_count())
if torch.cuda.is_available():
    print("device_name", torch.cuda.get_device_name(0))
PY
