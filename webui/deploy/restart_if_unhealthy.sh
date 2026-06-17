#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-/etc/jetson-yolo-webui.env}"
INSTALL_BASE="${INSTALL_BASE:-/opt/jetson-yolo-webui}"
LOG_FILE="${INSTALL_BASE}/runtime/healthcheck.log"
HEALTHCHECK="${INSTALL_BASE}/current/webui/deploy/healthcheck.sh"
SERVICE_NAME="${SERVICE_NAME:-jetson-yolo-webui.service}"

mkdir -p "$(dirname "$LOG_FILE")"

ts() {
  date -Is
}

if "$HEALTHCHECK" >/tmp/jetson-yolo-webui-healthcheck.out 2>&1; then
  printf '%s OK healthcheck passed\n' "$(ts)" >> "$LOG_FILE"
  exit 0
else
  rc=$?
fi

{
  printf '%s WARN healthcheck failed rc=%s\n' "$(ts)" "$rc"
  sed 's/^/  /' /tmp/jetson-yolo-webui-healthcheck.out || true
  printf '%s INFO restarting %s\n' "$(ts)" "$SERVICE_NAME"
} >> "$LOG_FILE"

systemctl restart "$SERVICE_NAME"
exit 0
