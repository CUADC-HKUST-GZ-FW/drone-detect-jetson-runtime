#!/usr/bin/env bash
set -euo pipefail

NODE="jetson"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --node)
      NODE="$2"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TS="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="$ROOT_DIR/results/inventory/${NODE}-${TS}"
mkdir -p "$OUT_DIR"

COMMANDS_LOG="$OUT_DIR/commands.log"
exec > >(tee "$OUT_DIR/inventory.log") 2>&1

run_cmd() {
  local name="$1"
  shift
  echo "===== $name ====="
  printf '%q ' "$@" | tee -a "$COMMANDS_LOG"
  echo | tee -a "$COMMANDS_LOG"
  "$@" || true
  echo
}

echo "node=$NODE"
echo "timestamp=$(date -Is)"
echo "root_dir=$ROOT_DIR"

run_cmd identity bash -lc 'hostname; whoami; date -Is'
run_cmd system bash -lc 'uname -a; cat /etc/os-release 2>/dev/null || true; cat /etc/nv_tegra_release 2>/dev/null || true'
run_cmd versions bash -lc 'for c in python3 pip3 git ffmpeg gst-launch-1.0 gst-inspect-1.0 ip tc iperf3 nvidia-smi tegrastats nvcc; do echo "## $c"; if command -v "$c" >/dev/null 2>&1; then command -v "$c"; case "$c" in python3) python3 --version;; pip3) pip3 --version;; ffmpeg) ffmpeg -version | head -1;; gst-launch-1.0) gst-launch-1.0 --version | head -2;; gst-inspect-1.0) gst-inspect-1.0 --version | head -2;; iperf3) iperf3 --version | head -1;; nvcc) nvcc --version | tail -2;; git) git --version;; tc) tc -V;; ip) ip -V;; *) "$c" --help 2>&1 | head -3 || true;; esac; else echo missing; fi; done'
run_cmd python_modules python3 - <<'PY'
import importlib

for name in ["cv2", "torch", "torchvision", "ultralytics", "numpy", "yaml", "psutil"]:
    try:
        mod = importlib.import_module(name)
        print(f"{name}: ok {getattr(mod, '__version__', 'unknown')}")
    except Exception as exc:
        print(f"{name}: missing_or_error {type(exc).__name__}: {exc}")
PY
run_cmd network bash -lc 'ip -br addr; echo "--- routes ---"; ip route; echo "--- route to 1.1.1.1 ---"; ip route get 1.1.1.1 2>/dev/null || true'
run_cmd tc_status bash -lc 'tc qdisc show 2>/dev/null || true; tc class show 2>/dev/null || true; tc filter show 2>/dev/null || true'
run_cmd media_scan bash -lc 'find "$PWD" "$HOME/Videos" "$HOME" -maxdepth 3 -type f \( -iname "*.mp4" -o -iname "*.avi" -o -iname "*.mkv" -o -iname "*.mov" \) 2>/dev/null | head -50'
run_cmd gstreamer_h264 bash -lc 'for e in nvv4l2h264enc x264enc openh264enc rtph264pay rtph264depay fpsdisplaysink; do if gst-inspect-1.0 "$e" >/dev/null 2>&1; then echo "$e: ok"; else echo "$e: missing"; fi; done'

cat > "$OUT_DIR/summary.txt" <<EOF
node=$NODE
timestamp=$TS
output_dir=$OUT_DIR
EOF

echo "inventory output: $OUT_DIR"

