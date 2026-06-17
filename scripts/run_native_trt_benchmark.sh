#!/usr/bin/env bash
set -euo pipefail

ENGINE="${1:-models/trt/yolo26n_1024_fp16_ultralytics.raw.engine}"
VIDEO="${2:-assets/test_20s.mp4}"
WARMUP="${WARMUP:-3}"
MEASURE="${MEASURE:-20}"
TARGET="${TARGET:-1024}"
SLOTS="${SLOTS:-4}"
CAPS_W="${CAPS_W:-1024}"
CAPS_H="${CAPS_H:-576}"
MODE="${MODE:-pipeline}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x native/build/native_trt_video_pipeline_runner ]]; then
  make -C native -j"$(nproc)"
fi

case "$MODE" in
  pipeline)
    exec native/build/native_trt_video_pipeline_runner "$ENGINE" "$VIDEO" "$WARMUP" "$MEASURE" "$TARGET" "$SLOTS" "$CAPS_W" "$CAPS_H"
    ;;
  strict)
    exec native/build/native_trt_video_strict_square_runner "$ENGINE" "$VIDEO" "$WARMUP" "$MEASURE" "$TARGET" "$SLOTS" "$CAPS_W" "$CAPS_H"
    ;;
  *)
    echo "unknown MODE=$MODE; use pipeline or strict" >&2
    exit 2
    ;;
esac
