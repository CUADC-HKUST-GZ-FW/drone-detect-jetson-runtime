#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-/etc/jetson-yolo-webui.env}"

if [ "$(id -u)" -ne 0 ] && [ ! -w "$ENV_FILE" ]; then
  echo "Run with sudo or set ENV_FILE to a writable path."
  exit 1
fi

TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"

if [ ! -f "$ENV_FILE" ]; then
  mkdir -p "$(dirname "$ENV_FILE")"
  touch "$ENV_FILE"
fi

if grep -q '^JETSON_WEBUI_TOKEN=' "$ENV_FILE"; then
  tmp="$(mktemp)"
  sed "s|^JETSON_WEBUI_TOKEN=.*|JETSON_WEBUI_TOKEN=${TOKEN}|" "$ENV_FILE" > "$tmp"
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
else
  printf '\nJETSON_WEBUI_TOKEN=%s\n' "$TOKEN" >> "$ENV_FILE"
fi

chmod 600 "$ENV_FILE" 2>/dev/null || true

echo "Updated $ENV_FILE"
echo "JETSON_WEBUI_TOKEN=$TOKEN"
echo "Restart with:"
echo "  sudo systemctl restart jetson-yolo-webui"

