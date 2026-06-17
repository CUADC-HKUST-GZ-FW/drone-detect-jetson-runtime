# Changelog

## 0.6.0 - 2026-06-06

Frontend authentication ergonomics:

- added public `/api/auth` metadata endpoint without exposing tokens
- added WebUI `Set Token` and `Clear Token` controls
- updated OpenAPI and E2E coverage for auth metadata
- added responsive top-action layout for token controls

## 0.5.0 - 2026-06-06

Access configuration and tokenized verification:

- added `webui/deploy/configure_access.sh` for repeatable host, port, CORS, and token setup
- made non-loopback access configuration auto-generate a token when none is supplied
- made `verify_deployment.sh` source `/etc/jetson-yolo-webui.env`, so token-protected deployments verify without manual headers
- tightened installed env-file permissions to `600`
- added E2E coverage for token-protected deployment verification and access configuration

## 0.4.0 - 2026-06-06

Deployment verification and external integration:

- added `/api/actions` with allowlisted action metadata and parameter hints
- added `/api/diagnostics` with redacted service, path, disk, command, systemd, and security state
- added WebUI diagnostics panel on the Overview page
- added `webui/deploy/verify_deployment.sh` for repeatable post-install validation
- expanded API examples to include bootstrap, actions, diagnostics, and OpenAPI endpoints

## 0.3.0 - 2026-06-06

WebUI readiness and integration hardening:

- added `/api/bootstrap` for first-run readiness, asset discovery, selected defaults, and config initialization
- added Overview readiness panel with one-click config initialization
- restricted `/api/log` reads to configured runtime, asset, and release roots
- restricted smoke-test runner/video/engine parameters to configured readable or runnable roots
- added frontend escaping for dynamic asset, run, and status fields
- made the deploy installer restart already-running services during upgrades
- added explicit `JETSON_WEBUI_RUNTIME_ROOT` and env-file migration for stable runtime data across upgrades
- documented bootstrap API and root allowlists
- kept deploy package macOS xattr-free for clean Jetson extraction

## 0.2.0 - 2026-06-06

API and security hardening:

- added `/api/openapi.json`
- added WebUI API tab with curl examples
- added CORS configuration through `JETSON_WEBUI_CORS_ORIGIN`
- added standard security response headers
- added request body size limit through `JETSON_WEBUI_MAX_BODY_BYTES`
- switched token comparison to constant-time comparison
- removed query-string token authentication to avoid token leakage in logs
- refused non-loopback binding without `JETSON_WEBUI_TOKEN` unless explicitly overridden
- added automated E2E smoke test coverage

## 0.1.1 - 2026-06-06

Deployment hardening:

- systemd service now defaults to automatic restart with `Restart=always`
- install script enables and starts the WebUI service by default
- added healthcheck service/timer for automatic restart when `/api/health` fails
- healthcheck scripts load `/etc/jetson-yolo-webui.env`
- fixed deployed default config creation under `YOLO_PIPELINE_CONFIG`
- added startup and watchdog documentation

## 0.1.0 - 2026-06-06

Initial local documentation and WebUI service baseline.

Included:

- YOLO dataset and fine-tuning guide
- TensorRT export and validation guide
- high-performance C++/GStreamer pipeline guide
- cascade detection pipeline guide
- agent runbook
- troubleshooting checklists
- production deployment guide
- runtime config templates
- observability and operations guide
- release acceptance checklist
- lightweight WebUI service
- deployable service templates
- high-risk and low-resource design notes
