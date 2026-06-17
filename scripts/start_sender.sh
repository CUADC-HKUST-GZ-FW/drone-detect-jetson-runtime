#!/usr/bin/env bash
set -euo pipefail

DEST=""
PORT=5000
DURATION=60
SOURCE="testsrc"
WIDTH=1280
HEIGHT=720
FPS=30
BITRATE_KBIT=4000
PATTERN="ball"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --source) SOURCE="$2"; shift 2 ;;
    --width) WIDTH="$2"; shift 2 ;;
    --height) HEIGHT="$2"; shift 2 ;;
    --fps) FPS="$2"; shift 2 ;;
    --bitrate-kbit) BITRATE_KBIT="$2"; shift 2 ;;
    --pattern) PATTERN="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$DEST" ]]; then
  echo "--dest is required" >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "sending RTP/H264 UDP to ${DEST}:${PORT} for ${DURATION}s"

run_timeout() {
  set +e
  "$@"
  local rc=$?
  set -e
  if [[ "$rc" -eq 124 ]]; then
    echo "sender stopped after requested duration"
    return 0
  fi
  return "$rc"
}

run_testsrc_with_encoder() {
  run_timeout timeout --foreground "$DURATION" gst-launch-1.0 -e -v \
    videotestsrc is-live=true pattern="$PATTERN" \
    ! "video/x-raw,width=${WIDTH},height=${HEIGHT},framerate=${FPS}/1,format=I420" \
    "$@"
}

run_file_direct_h264() {
  run_timeout timeout --foreground "$DURATION" gst-launch-1.0 -e -v \
    filesrc location="$SOURCE" \
    ! qtdemux \
    ! h264parse config-interval=1 \
    ! rtph264pay pt=96 config-interval=1 \
    ! udpsink host="$DEST" port="$PORT" sync=false async=false
}

if [[ "$SOURCE" != "testsrc" && -f "$SOURCE" ]]; then
  echo "trying direct H.264 MP4 RTP packetization for $SOURCE"
  if run_file_direct_h264; then
    exit 0
  fi
  echo "direct file packetization failed; falling back to live videotestsrc" >&2
else
  echo "using live videotestsrc"
fi

run_encoded_testsrc() {
  if gst-inspect-1.0 nvv4l2h264enc >/dev/null 2>&1 && gst-inspect-1.0 nvvidconv >/dev/null 2>&1; then
    if run_testsrc_with_encoder \
      ! nvvidconv \
      ! "video/x-raw(memory:NVMM),format=NV12" \
      ! nvv4l2h264enc bitrate=$((BITRATE_KBIT * 1000)) \
      ! h264parse config-interval=1 \
      ! rtph264pay pt=96 config-interval=1 \
      ! udpsink host="$DEST" port="$PORT" sync=false async=false; then
      exit 0
    fi
    echo "hardware encoder path failed; falling back to software encoder" >&2
  fi

  if gst-inspect-1.0 x264enc >/dev/null 2>&1; then
    run_testsrc_with_encoder \
      ! x264enc tune=zerolatency speed-preset=ultrafast bitrate="$BITRATE_KBIT" \
      ! h264parse config-interval=1 \
      ! rtph264pay pt=96 config-interval=1 \
      ! udpsink host="$DEST" port="$PORT" sync=false async=false
  elif gst-inspect-1.0 openh264enc >/dev/null 2>&1; then
    run_testsrc_with_encoder \
      ! openh264enc bitrate=$((BITRATE_KBIT * 1000)) \
      ! h264parse config-interval=1 \
      ! rtph264pay pt=96 config-interval=1 \
      ! udpsink host="$DEST" port="$PORT" sync=false async=false
  else
    echo "no H.264 encoder found" >&2
    exit 1
  fi
}

run_encoded_testsrc
