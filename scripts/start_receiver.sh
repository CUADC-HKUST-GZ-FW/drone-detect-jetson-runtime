#!/usr/bin/env bash
set -euo pipefail

PORT=5000
DURATION=60
OUTPUT="results/baseline/received.ts"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p "$(dirname "$OUTPUT")"

echo "receiving RTP/H264 UDP on port $PORT for ${DURATION}s -> $OUTPUT"
set +e
timeout --foreground "$DURATION" gst-launch-1.0 -e -v \
  udpsrc port="$PORT" caps="application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000" \
  ! rtph264depay \
  ! h264parse \
  ! mpegtsmux \
  ! filesink location="$OUTPUT"
RC=$?
set -e
if [[ "$RC" -eq 124 ]]; then
  echo "receiver stopped after requested duration"
  exit 0
fi
exit "$RC"
