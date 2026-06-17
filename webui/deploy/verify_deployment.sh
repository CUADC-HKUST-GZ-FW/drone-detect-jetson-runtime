#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-/etc/jetson-yolo-webui.env}"
if [ -f "$ENV_FILE" ]; then
  if [ -r "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
  else
    echo "[INFO] $ENV_FILE is not readable; set JETSON_WEBUI_TOKEN or run verifier with sudo if auth is enabled." >&2
  fi
fi

HOST="${JETSON_WEBUI_HOST:-127.0.0.1}"
PORT="${JETSON_WEBUI_PORT:-8765}"
BASE_URL="${BASE_URL:-http://$HOST:$PORT}"
TOKEN="${JETSON_WEBUI_TOKEN:-}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

curl_json() {
  local path="$1"
  if [ -n "$TOKEN" ]; then
    curl -fsS -H "X-Auth-Token: $TOKEN" "$BASE_URL$path"
  else
    curl -fsS "$BASE_URL$path"
  fi
}

curl_health() {
  curl -fsS "$BASE_URL/api/health"
}

wait_for_health() {
  local out="$1"
  local i
  for i in $(seq 1 30); do
    if curl_health > "$out" 2>"$TMP_DIR/health.err"; then
      return 0
    fi
    sleep 1
  done
  cat "$TMP_DIR/health.err" >&2 || true
  return 1
}

json_check() {
  local file="$1"
  local expr="$2"
  python3 - "$file" "$expr" <<'PY'
import json
import sys

path, expr = sys.argv[1], sys.argv[2]
payload = json.load(open(path, encoding="utf-8"))
if not eval(expr, {"payload": payload}):
    raise SystemExit(f"check failed: {expr}")
PY
}

echo "[1/7] health"
wait_for_health "$TMP_DIR/health.json"
json_check "$TMP_DIR/health.json" "payload.get('ok') is True"

echo "[2/7] version"
curl_json "/api/version" > "$TMP_DIR/version.json"
json_check "$TMP_DIR/version.json" "'version' in payload and 'api_version' in payload"
curl -fsS "$BASE_URL/api/auth" > "$TMP_DIR/auth.json"
json_check "$TMP_DIR/auth.json" "'auth_required' in payload and payload.get('query_token_supported') is False"
python3 - "$TMP_DIR/version.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"version={payload['version']} api_version={payload['api_version']}")
PY

echo "[3/7] openapi/actions"
curl_json "/api/openapi.json" > "$TMP_DIR/openapi.json"
json_check "$TMP_DIR/openapi.json" "'/api/bootstrap' in payload.get('paths', {}) and '/api/diagnostics' in payload.get('paths', {})"
curl_json "/api/actions" > "$TMP_DIR/actions.json"
json_check "$TMP_DIR/actions.json" "'validate_config' in payload.get('actions', {}) and 'cascade_cpp_smoke' in payload.get('actions', {})"

echo "[4/7] bootstrap"
curl_json "/api/bootstrap" > "$TMP_DIR/bootstrap.json"
json_check "$TMP_DIR/bootstrap.json" "'readiness' in payload and 'selected_defaults' in payload and 'security' in payload"
python3 - "$TMP_DIR/bootstrap.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"bootstrap_ok={payload.get('ok')} asset_counts={payload.get('asset_counts')}")
PY

echo "[5/7] diagnostics"
curl_json "/api/diagnostics" > "$TMP_DIR/diagnostics.json"
json_check "$TMP_DIR/diagnostics.json" "'paths' in payload and 'commands' in payload and 'security' in payload"
python3 - "$TMP_DIR/diagnostics.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"diagnostics_ok={payload.get('ok')} bootstrap_ok={payload.get('bootstrap_ok')}")
PY

echo "[6/7] path protection"
if [ -n "$TOKEN" ]; then
  code="$(curl -sS -o "$TMP_DIR/forbidden.json" -w '%{http_code}' -H "X-Auth-Token: $TOKEN" "$BASE_URL/api/log?path=/etc/passwd")"
else
  code="$(curl -sS -o "$TMP_DIR/forbidden.json" -w '%{http_code}' "$BASE_URL/api/log?path=/etc/passwd")"
fi
if [ "$code" != "403" ]; then
  echo "expected /api/log?path=/etc/passwd to return 403, got $code"
  cat "$TMP_DIR/forbidden.json"
  exit 1
fi

echo "[7/7] systemd state if available"
if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files jetson-yolo-webui.service >/dev/null 2>&1; then
  systemctl is-active --quiet jetson-yolo-webui.service
  systemctl is-enabled --quiet jetson-yolo-webui.service
  if systemctl list-unit-files jetson-yolo-webui-healthcheck.timer >/dev/null 2>&1; then
    systemctl is-active --quiet jetson-yolo-webui-healthcheck.timer
    systemctl is-enabled --quiet jetson-yolo-webui-healthcheck.timer
  fi
  echo "systemd=ok"
else
  echo "systemd=skipped"
fi

echo "VERIFY_DEPLOYMENT_OK base_url=$BASE_URL"
