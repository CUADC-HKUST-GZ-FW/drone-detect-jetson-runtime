# Jetson YOLO Pipeline WebUI

Lightweight one-stop WebUI for configuring and smoke-testing a Jetson YOLO TensorRT/GStreamer pipeline.

It uses only Python standard library modules and static frontend files.

The Overview page includes readiness checks and config initialization. The same flow is available through:

```text
GET /api/bootstrap
POST /api/bootstrap
```

External integrations can also discover supported actions and deployment health:

```text
GET /api/auth
GET /api/actions
GET /api/diagnostics
```

The WebUI header includes `Set Token` and `Clear Token` controls for token-protected deployments.

## Run

```bash
cd ~/jetson_yolo_pipeline_docs/webui
python3 server.py --host 0.0.0.0 --port 8765
```

Open:

```text
http://<jetson-ip>:8765
```

## Environment

```bash
export YOLO_PIPELINE_CONFIG=/opt/yolo-pipeline/current/config/pipeline_config.yaml
export JETSON_ASSET_ROOT=$HOME/jetson_benchmark_assets
export JETSON_RELEASE_ROOT=/opt/yolo-pipeline/current
export JETSON_DOCS_ROOT=$HOME/jetson_yolo_pipeline_docs
```

Optional access token:

```bash
export JETSON_WEBUI_TOKEN='replace-with-a-long-random-token'
```

## Deploy

```bash
sudo webui/deploy/install_webui.sh
```

The installer enables and starts:

```text
jetson-yolo-webui.service
jetson-yolo-webui-healthcheck.timer
```

The main service uses `Restart=always`. The timer runs a periodic `/api/health` check and restarts the service when health fails.

## Safety

The API does not expose arbitrary command execution. Test buttons map to fixed allowlisted actions in `server.py`.

Log reads and smoke-test runner parameters are restricted to configured roots. Extend them only when needed:

```bash
export JETSON_WEBUI_READ_ROOTS='/path/to/reports'
export JETSON_WEBUI_RUN_ROOTS='/opt/my-pipeline'
```

API and auth details:

```text
API.md
```

Generate or rotate a token:

```bash
sudo webui/deploy/generate_token.sh
sudo systemctl restart jetson-yolo-webui
```

Configure local or LAN access without manual env editing:

```bash
sudo webui/deploy/configure_access.sh --host 127.0.0.1 --generate-token
sudo webui/deploy/configure_access.sh --host 0.0.0.0 --generate-token
```

Verify an installed service:

```bash
BASE_URL=http://127.0.0.1:8765 webui/deploy/verify_deployment.sh
```
