# Jetson YOLO WebUI API

Base URL:

```text
http://<host>:8765
```

OpenAPI:

```text
GET /api/openapi.json
```

Auth metadata:

```text
GET /api/auth
```

## Authentication

Set:

```bash
export JETSON_WEBUI_TOKEN='long-random-token'
```

Authenticated requests may use either header:

```text
X-Auth-Token: <token>
Authorization: Bearer <token>
```

`/api/health` is intentionally unauthenticated for systemd health checks.

Query-string tokens are not supported because they leak into logs.

## External Binding Safety

The server refuses to bind to non-loopback addresses without a token.

Allowed without token:

```text
127.0.0.1
localhost
::1
```

For remote access, prefer SSH forwarding:

```bash
ssh -L 8765:127.0.0.1:8765 jetson@<jetson-ip>
```

For LAN access:

```bash
sudo /opt/jetson-yolo-webui/current/webui/deploy/configure_access.sh \
  --host 0.0.0.0 \
  --generate-token
```

The configurator restarts the service and prints a generated token once.

Only override this guard in an isolated lab:

```bash
export JETSON_WEBUI_ALLOW_NO_AUTH_EXTERNAL=1
```

## CORS

By default, CORS is disabled.

Enable a specific origin:

```bash
export JETSON_WEBUI_CORS_ORIGIN='http://192.168.1.10:3000'
```

Multiple origins:

```bash
export JETSON_WEBUI_CORS_ORIGIN='http://a.local:3000,http://b.local:3000'
```

Wildcard, for isolated labs only:

```bash
export JETSON_WEBUI_CORS_ORIGIN='*'
```

## Request Size

Default JSON request body limit:

```text
1048576 bytes
```

Override:

```bash
export JETSON_WEBUI_MAX_BODY_BYTES=2097152
```

## Common Calls

Health:

```bash
curl -fsS http://127.0.0.1:8765/api/health
```

Status:

```bash
curl -fsS -H "X-Auth-Token: $JETSON_WEBUI_TOKEN" \
  http://127.0.0.1:8765/api/status
```

Auth metadata:

```bash
curl -fsS http://127.0.0.1:8765/api/auth
```

Bootstrap readiness and selected defaults:

```bash
curl -fsS -H "X-Auth-Token: $JETSON_WEBUI_TOKEN" \
  http://127.0.0.1:8765/api/bootstrap
```

List allowlisted actions and parameter hints:

```bash
curl -fsS -H "X-Auth-Token: $JETSON_WEBUI_TOKEN" \
  http://127.0.0.1:8765/api/actions
```

Deployment diagnostics:

```bash
curl -fsS -H "X-Auth-Token: $JETSON_WEBUI_TOKEN" \
  http://127.0.0.1:8765/api/diagnostics
```

Initialize or repair runtime config from discovered assets:

```bash
curl -fsS \
  -H "X-Auth-Token: $JETSON_WEBUI_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"write_config":true,"force":false}' \
  http://127.0.0.1:8765/api/bootstrap
```

Read config:

```bash
curl -fsS -H "X-Auth-Token: $JETSON_WEBUI_TOKEN" \
  http://127.0.0.1:8765/api/config
```

Run config validation:

```bash
curl -fsS \
  -H "X-Auth-Token: $JETSON_WEBUI_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action":"validate_config","params":{}}' \
  http://127.0.0.1:8765/api/run
```

List runs:

```bash
curl -fsS -H "X-Auth-Token: $JETSON_WEBUI_TOKEN" \
  http://127.0.0.1:8765/api/runs
```

## Allowlisted Actions

```text
validate_config
tegrastats_5s
gst_hwdecode_smoke
strict1024_cpp_smoke
cascade_cpp_smoke
```

The API does not provide arbitrary shell execution.

Post-install verification:

```bash
BASE_URL=http://127.0.0.1:8765 \
  /opt/jetson-yolo-webui/current/webui/deploy/verify_deployment.sh
```

`verify_deployment.sh` reads `/etc/jetson-yolo-webui.env` when readable. After token auth is enabled and the env file is `600`, run it with `sudo` or pass `JETSON_WEBUI_TOKEN` explicitly.

## Path Allowlists

The log API and smoke-test runner parameters are restricted to configured roots.

Readable roots default to:

```text
JETSON_ASSET_ROOT
JETSON_RELEASE_ROOT
webui/runtime
webui/runtime/runs
```

Add additional read-only log/report roots with:

```bash
export JETSON_WEBUI_READ_ROOTS='/path/a:/path/b'
```

Runnable roots default to:

```text
JETSON_ASSET_ROOT
JETSON_RELEASE_ROOT
webui/runtime/runs
~/jetson_90fps_yolo26n1024
~/jetson_cascade_benchmark
```

Add additional runner/engine roots with:

```bash
export JETSON_WEBUI_RUN_ROOTS='/opt/my-pipeline:/home/user/my-runners'
```
