# 11 Lightweight WebUI Service

This document describes the lightweight one-stop WebUI service for Jetson YOLO pipeline management.

Implementation path:

```text
webui/
  server.py
  static/
    index.html
    styles.css
    app.js
  systemd/
    jetson-yolo-webui.service
```

## Scope

The WebUI is for development and controlled lab operation.

It supports:

- first-run readiness checks and config initialization
- viewing Jetson/runtime status
- viewing and editing pipeline config text
- listing known videos, models, engines, logs, and reports
- running allowlisted smoke tests
- tailing run logs
- opening release checklist and docs from one place

It does not:

- install system packages
- install DeepStream
- run arbitrary shell commands
- change `nvpmodel` mode ids
- replace production health monitoring

## Start Locally

From the docs directory:

```bash
cd ~/jetson_yolo_pipeline_docs/webui
python3 server.py --host 0.0.0.0 --port 8765
```

Open:

```text
http://<jetson-ip>:8765
```

For local-only access:

```bash
python3 server.py --host 127.0.0.1 --port 8765
```

## Useful Environment Variables

```bash
export YOLO_PIPELINE_CONFIG=/opt/yolo-pipeline/current/config/pipeline_config.yaml
export JETSON_ASSET_ROOT=$HOME/jetson_benchmark_assets
export JETSON_RELEASE_ROOT=/opt/yolo-pipeline/current
export JETSON_DOCS_ROOT=$HOME/jetson_yolo_pipeline_docs
```

If `YOLO_PIPELINE_CONFIG` is unset, the service edits a runtime copy under:

```text
webui/runtime/pipeline_config.yaml
```

The service can discover assets, select likely defaults, and initialize the runtime config:

```bash
curl -fsS -H "X-Auth-Token: $JETSON_WEBUI_TOKEN" \
  http://127.0.0.1:8765/api/bootstrap

curl -fsS \
  -H "X-Auth-Token: $JETSON_WEBUI_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"write_config":true,"force":false}' \
  http://127.0.0.1:8765/api/bootstrap
```

External integrations can enumerate actions and inspect deployment health without scraping the UI:

```bash
curl -fsS http://127.0.0.1:8765/api/auth

curl -fsS -H "X-Auth-Token: $JETSON_WEBUI_TOKEN" \
  http://127.0.0.1:8765/api/actions

curl -fsS -H "X-Auth-Token: $JETSON_WEBUI_TOKEN" \
  http://127.0.0.1:8765/api/diagnostics
```

For token-protected deployments, use the header `Set Token` and `Clear Token` controls to manage the browser's local token storage.

For deployable service installs, use:

```text
webui/deploy/install_webui.sh
webui/deploy/jetson-yolo-webui.env.example
webui/deploy/jetson-yolo-webui.service
webui/deploy/jetson-yolo-webui-healthcheck.service
webui/deploy/jetson-yolo-webui-healthcheck.timer
```

The installer enables and starts the service and healthcheck timer by default:

```text
jetson-yolo-webui.service
  - starts on boot
  - restarts automatically with Restart=always

jetson-yolo-webui-healthcheck.timer
  - starts on boot
  - checks /api/health every 30 seconds
  - restarts the service if health fails
```

To install without starting services immediately:

```bash
sudo ENABLE_SERVICE=0 ENABLE_HEALTHCHECK=0 webui/deploy/install_webui.sh
```

Set an access token when the service is reachable from other machines:

```bash
export JETSON_WEBUI_TOKEN='replace-with-a-long-random-token'
```

The frontend will prompt for this token and send it as `X-Auth-Token`.

Generate or rotate a token on a deployed host:

```bash
sudo /opt/jetson-yolo-webui/current/webui/deploy/generate_token.sh
sudo systemctl restart jetson-yolo-webui
```

Configure access without hand-editing `/etc/jetson-yolo-webui.env`:

```bash
sudo /opt/jetson-yolo-webui/current/webui/deploy/configure_access.sh \
  --host 127.0.0.1 \
  --generate-token

sudo /opt/jetson-yolo-webui/current/webui/deploy/configure_access.sh \
  --host 0.0.0.0 \
  --generate-token
```

When a non-loopback host is selected and no token exists, the configurator generates one automatically.

External API details are in:

```text
webui/API.md
```

After deployment:

```bash
systemctl status jetson-yolo-webui --no-pager
systemctl status jetson-yolo-webui-healthcheck.timer --no-pager
journalctl -u jetson-yolo-webui -n 100 --no-pager
```

Run the bundled deployment verifier:

```bash
BASE_URL=http://127.0.0.1:8765 \
  /opt/jetson-yolo-webui/current/webui/deploy/verify_deployment.sh
```

## Allowlisted Actions

The server currently supports these actions:

```text
validate_config
tegrastats_5s
gst_hwdecode_smoke
strict1024_cpp_smoke
cascade_cpp_smoke
```

Action behavior:

- `validate_config` checks config text and key paths.
- `tegrastats_5s` runs a short tegrastats capture.
- `gst_hwdecode_smoke` validates H.264 hardware decode with `nvv4l2decoder`.
- `strict1024_cpp_smoke` runs the existing strict 1024 C++ TensorRT runner if present.
- `cascade_cpp_smoke` runs the existing cascade C++ runner if present.

Each run writes:

```text
webui/runtime/runs/<run_id>.json
webui/runtime/runs/<run_id>.log
```

Runner, video, and engine paths are restricted to configured roots. Defaults include `JETSON_ASSET_ROOT`, `JETSON_RELEASE_ROOT`, and the known benchmark runner directories. Extend only for trusted local deployments:

```bash
export JETSON_WEBUI_READ_ROOTS=/path/to/extra/reports
export JETSON_WEBUI_RUN_ROOTS=/opt/my-pipeline:/home/user/my-runners
```

## Security Notes

Bind to `127.0.0.1` unless you are on a trusted lab network.

If remote access is needed, prefer SSH port forwarding:

```bash
ssh -L 8765:127.0.0.1:8765 jetson@<jetson-ip>
```

Do not expose this service to the public internet. It is a lab management console.

For high-risk or low-resource deployments, use the constraints in:

```text
13_high_risk_low_resource_design.md
```

## Production Use

The production pipeline should still be managed by:

- immutable release directories
- systemd service for the pipeline runner
- structured logs and metrics
- acceptance report and rollback plan

The WebUI is a control plane for setup, smoke tests, and operational inspection.
