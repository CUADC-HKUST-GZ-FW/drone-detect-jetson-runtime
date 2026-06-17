#!/usr/bin/env bash
set -euo pipefail

DURATION=60
OUTPUT="assets/test_60s.mp4"
WIDTH=1280
HEIGHT=720
FPS=30

while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration) DURATION="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    --width) WIDTH="$2"; shift 2 ;;
    --height) HEIGHT="$2"; shift 2 ;;
    --fps) FPS="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p "$(dirname "$OUTPUT")"

BUFFERS=$((DURATION * FPS))

echo "writing $OUTPUT duration=${DURATION}s ${WIDTH}x${HEIGHT}@${FPS}"

if gst-inspect-1.0 nvv4l2h264enc >/dev/null 2>&1 && gst-inspect-1.0 nvvidconv >/dev/null 2>&1; then
  if gst-launch-1.0 -e \
    videotestsrc num-buffers="$BUFFERS" pattern=ball \
    ! "video/x-raw,width=${WIDTH},height=${HEIGHT},framerate=${FPS}/1,format=I420" \
    ! nvvidconv \
    ! "video/x-raw(memory:NVMM),format=NV12" \
    ! nvv4l2h264enc bitrate=4000000 \
    ! h264parse \
    ! mp4mux \
    ! filesink location="$OUTPUT"; then
    exit 0
  fi
  echo "hardware encoder path failed; falling back to software encoder" >&2
fi

if gst-inspect-1.0 x264enc >/dev/null 2>&1; then
  gst-launch-1.0 -e \
    videotestsrc num-buffers="$BUFFERS" pattern=ball \
    ! "video/x-raw,width=${WIDTH},height=${HEIGHT},framerate=${FPS}/1,format=I420" \
    ! x264enc tune=zerolatency speed-preset=ultrafast bitrate=4000 \
    ! h264parse \
    ! mp4mux \
    ! filesink location="$OUTPUT"
elif gst-inspect-1.0 openh264enc >/dev/null 2>&1; then
  gst-launch-1.0 -e \
    videotestsrc num-buffers="$BUFFERS" pattern=ball \
    ! "video/x-raw,width=${WIDTH},height=${HEIGHT},framerate=${FPS}/1,format=I420" \
    ! openh264enc bitrate=4000000 \
    ! h264parse \
    ! mp4mux \
    ! filesink location="$OUTPUT"
else
  echo "no H.264 encoder found" >&2
  exit 1
fi
