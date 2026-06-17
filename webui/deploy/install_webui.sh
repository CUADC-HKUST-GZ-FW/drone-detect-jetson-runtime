#!/usr/bin/env bash
set -euo pipefail

SRC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$SRC_ROOT/VERSION")"
INSTALL_BASE="${INSTALL_BASE:-/opt/jetson-yolo-webui}"
RELEASE_DIR="$INSTALL_BASE/releases/$VERSION"
CURRENT_LINK="$INSTALL_BASE/current"
ENV_FILE="${ENV_FILE:-/etc/jetson-yolo-webui.env}"
SERVICE_FILE="/etc/systemd/system/jetson-yolo-webui.service"
HEALTHCHECK_SERVICE_FILE="/etc/systemd/system/jetson-yolo-webui-healthcheck.service"
HEALTHCHECK_TIMER_FILE="/etc/systemd/system/jetson-yolo-webui-healthcheck.timer"
ENABLE_SERVICE="${ENABLE_SERVICE:-1}"
ENABLE_HEALTHCHECK="${ENABLE_HEALTHCHECK:-1}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo."
  exit 1
fi

mkdir -p "$INSTALL_BASE/releases" "$INSTALL_BASE/runtime"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.DS_Store' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'dist' \
  --exclude 'webui/runtime' \
  "$SRC_ROOT/" "$RELEASE_DIR/"

ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"

if [ ! -f "$ENV_FILE" ]; then
  cp "$SRC_ROOT/webui/deploy/jetson-yolo-webui.env.example" "$ENV_FILE"
fi

ensure_env_key() {
  local key="$1"
  local value="$2"
  if ! grep -qE "^${key}=" "$ENV_FILE"; then
    printf '\n%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

ensure_env_key "JETSON_WEBUI_RUNTIME_ROOT" "$INSTALL_BASE/runtime"
ensure_env_key "JETSON_WEBUI_READ_ROOTS" ""
ensure_env_key "JETSON_WEBUI_RUN_ROOTS" ""
chmod 600 "$ENV_FILE" 2>/dev/null || true

cp "$SRC_ROOT/webui/deploy/jetson-yolo-webui.service" "$SERVICE_FILE"
cp "$SRC_ROOT/webui/deploy/jetson-yolo-webui-healthcheck.service" "$HEALTHCHECK_SERVICE_FILE"
cp "$SRC_ROOT/webui/deploy/jetson-yolo-webui-healthcheck.timer" "$HEALTHCHECK_TIMER_FILE"
systemctl daemon-reload

if [ "$ENABLE_SERVICE" = "1" ]; then
  systemctl enable jetson-yolo-webui.service
  if systemctl is-active --quiet jetson-yolo-webui.service; then
    systemctl restart jetson-yolo-webui.service
  else
    systemctl start jetson-yolo-webui.service
  fi
fi

if [ "$ENABLE_HEALTHCHECK" = "1" ]; then
  systemctl enable jetson-yolo-webui-healthcheck.timer
  if systemctl is-active --quiet jetson-yolo-webui-healthcheck.timer; then
    systemctl restart jetson-yolo-webui-healthcheck.timer
  else
    systemctl start jetson-yolo-webui-healthcheck.timer
  fi
fi

echo "Installed Jetson YOLO WebUI $VERSION"
echo "Environment file: $ENV_FILE"
echo "Service status:"
echo "  systemctl status jetson-yolo-webui --no-pager"
echo "Healthcheck timer:"
echo "  systemctl status jetson-yolo-webui-healthcheck.timer --no-pager"
echo "Access configuration:"
echo "  sudo $CURRENT_LINK/webui/deploy/configure_access.sh --host 127.0.0.1 --generate-token"
echo "Deployment verification:"
echo "  $CURRENT_LINK/webui/deploy/verify_deployment.sh"
