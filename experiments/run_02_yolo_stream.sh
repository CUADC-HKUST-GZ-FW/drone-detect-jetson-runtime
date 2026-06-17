#!/usr/bin/env bash
set -euo pipefail

SOURCE="assets/test_60s.mp4"
MODEL="yolov26n"
DURATION=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SOURCE="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --max-frames) DURATION="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
OUT_DIR="results/yolo/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"

CMD=(python3 scripts/run_yolo_video.py --model "$MODEL" --source "$SOURCE" --output-dir "$OUT_DIR")
if [[ "$DURATION" -gt 0 ]]; then
  CMD+=(--max-frames "$DURATION")
fi
printf '%q ' "${CMD[@]}" > "$OUT_DIR/commands.log"
echo >> "$OUT_DIR/commands.log"
"${CMD[@]}" 2>&1 | tee "$OUT_DIR/yolo.log"

