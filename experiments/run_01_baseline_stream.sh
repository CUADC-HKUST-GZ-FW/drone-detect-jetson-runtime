#!/usr/bin/env bash
set -euo pipefail

DEST=""
ROLE=""
DURATION=60
PORT=5000
SOURCE="testsrc"
INTERFACE="eth0"
PATTERN="ball"
BITRATE_KBIT=4000

while [[ $# -gt 0 ]]; do
  case "$1" in
    --role) ROLE="$2"; shift 2 ;;
    --dest) DEST="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --source) SOURCE="$2"; shift 2 ;;
    --interface) INTERFACE="$2"; shift 2 ;;
    --pattern) PATTERN="$2"; shift 2 ;;
    --bitrate-kbit) BITRATE_KBIT="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
OUT_DIR="results/baseline/$(date +%Y%m%d_%H%M%S)-$ROLE"
mkdir -p "$OUT_DIR"

{
  echo "pwd=$ROOT_DIR"
  echo "role=$ROLE"
  echo "duration=$DURATION"
  echo "port=$PORT"
} > "$OUT_DIR/commands.log"

if [[ "$ROLE" == "receiver" ]]; then
  python3 scripts/collect_metrics.py --interface "$INTERFACE" --duration "$DURATION" --output "$OUT_DIR/metrics.jsonl" --include-tc > "$OUT_DIR/metrics.log" 2>&1 &
  METRICS_PID=$!
  bash scripts/start_receiver.sh --port "$PORT" --duration "$DURATION" --output "$OUT_DIR/received.ts" 2>&1 | tee "$OUT_DIR/receiver.log"
  wait "$METRICS_PID" || true
elif [[ "$ROLE" == "sender" ]]; then
  if [[ -z "$DEST" ]]; then
    echo "--dest is required for sender" >&2
    exit 2
  fi
  python3 scripts/collect_metrics.py --interface "$INTERFACE" --duration "$DURATION" --output "$OUT_DIR/metrics.jsonl" --include-tc > "$OUT_DIR/metrics.log" 2>&1 &
  METRICS_PID=$!
  bash scripts/start_sender.sh --dest "$DEST" --port "$PORT" --duration "$DURATION" --source "$SOURCE" --pattern "$PATTERN" --bitrate-kbit "$BITRATE_KBIT" 2>&1 | tee "$OUT_DIR/sender.log"
  wait "$METRICS_PID" || true
else
  echo "--role sender|receiver is required" >&2
  exit 2
fi

cat > "$OUT_DIR/summary.md" <<EOF
# Baseline Stream Summary

- Role: $ROLE
- Duration: ${DURATION}s
- Port: $PORT
- Output: $OUT_DIR
EOF

echo "$OUT_DIR"
