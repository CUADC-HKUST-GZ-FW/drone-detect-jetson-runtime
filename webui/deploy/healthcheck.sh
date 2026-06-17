#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-/etc/jetson-yolo-webui.env}"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

HOST="${JETSON_WEBUI_HOST:-127.0.0.1}"
PORT="${JETSON_WEBUI_PORT:-8765}"
TOKEN="${JETSON_WEBUI_TOKEN:-}"

if [ -n "$TOKEN" ]; then
  curl -fsS -H "X-Auth-Token: $TOKEN" "http://$HOST:$PORT/api/health"
else
  curl -fsS "http://$HOST:$PORT/api/health"
fi
