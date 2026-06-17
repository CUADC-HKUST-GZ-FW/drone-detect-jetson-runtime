# 12 Service Deployment And Versioning

This document defines how to manage the WebUI and pipeline docs as a deployable service package.

The current phase uses local git only. A GitHub remote can be added later after the package layout and release process are stable.

## Repository Layout

```text
jetson_yolo_pipeline_docs/
  VERSION
  CHANGELOG.md
  README.md
  01_*.md ... 13_*.md
  templates/
  webui/
    server.py
    static/
    deploy/
    systemd/
```

`webui/runtime/` is intentionally ignored by git. It contains local logs, generated configs, and run records.

## Version Policy

Use semantic versioning:

```text
MAJOR.MINOR.PATCH
```

Suggested meaning:

- MAJOR: incompatible config/API changes
- MINOR: new WebUI features, new docs, new deployment templates
- PATCH: fixes that do not change config or API contracts

Update these files together:

```text
VERSION
CHANGELOG.md
webui/version.json
```

## Local Git Workflow

Initialize once:

```bash
cd ~/jetson_yolo_pipeline_docs
git init
git add .
git commit -m "Initial Jetson YOLO pipeline docs and WebUI"
```

Daily workflow:

```bash
git status --short
git diff
git add README.md webui/server.py
git commit -m "Improve WebUI deployment hardening"
```

Before pushing to GitHub later:

```bash
git log --oneline --decorate --graph --all
git status --short
```

Do not commit:

- runtime logs
- generated benchmark outputs
- SSH keys
- access tokens
- local camera URLs with credentials
- large model weights or TensorRT engines unless a release artifact policy explicitly allows it

## Packaging

Create a release tarball from a clean git checkout:

```bash
cd ~/jetson_yolo_pipeline_docs
webui/deploy/package_release.sh
```

Expected output:

```text
dist/jetson-yolo-pipeline-docs-<VERSION>.tar.gz
```

## Install On Another Machine

Copy the tarball and run:

```bash
tar -xzf jetson-yolo-pipeline-docs-0.6.0.tar.gz
cd jetson-yolo-pipeline-docs-0.6.0
sudo webui/deploy/install_webui.sh
```

Default install path:

```text
/opt/jetson-yolo-webui
```

Default config:

```text
/etc/jetson-yolo-webui.env
```

The install script is idempotent. It should not delete user data.

By default the installer runs:

```bash
systemctl enable --now jetson-yolo-webui.service
systemctl enable --now jetson-yolo-webui-healthcheck.timer
```

This gives the deployed WebUI:

- boot-time autostart
- automatic process restart with `Restart=always`
- periodic `/api/health` checks
- automatic service restart when the healthcheck fails

Disable immediate startup only when building an image or staging config:

```bash
sudo ENABLE_SERVICE=0 ENABLE_HEALTHCHECK=0 webui/deploy/install_webui.sh
```

## Service Configuration

Use:

```text
webui/deploy/jetson-yolo-webui.env.example
```

Important variables:

```bash
JETSON_WEBUI_HOST=127.0.0.1
JETSON_WEBUI_PORT=8765
JETSON_WEBUI_TOKEN=
JETSON_WEBUI_CORS_ORIGIN=
JETSON_WEBUI_MAX_BODY_BYTES=1048576
JETSON_WEBUI_ALLOW_NO_AUTH_EXTERNAL=0
JETSON_WEBUI_READ_ROOTS=
JETSON_WEBUI_RUN_ROOTS=
JETSON_WEBUI_RUNTIME_ROOT=/opt/jetson-yolo-webui/runtime
JETSON_DOCS_ROOT=/opt/jetson-yolo-webui/current
JETSON_ASSET_ROOT=/home/jetson/jetson_benchmark_assets
JETSON_RELEASE_ROOT=/opt/yolo-pipeline/current
YOLO_PIPELINE_CONFIG=/opt/jetson-yolo-webui/runtime/pipeline_config.yaml
```

Set `JETSON_WEBUI_TOKEN` when binding to anything other than `127.0.0.1`.

Generate or rotate a token:

```bash
sudo /opt/jetson-yolo-webui/current/webui/deploy/generate_token.sh
sudo systemctl restart jetson-yolo-webui
```

Configure access idempotently:

```bash
sudo /opt/jetson-yolo-webui/current/webui/deploy/configure_access.sh \
  --host 127.0.0.1 \
  --generate-token

sudo /opt/jetson-yolo-webui/current/webui/deploy/configure_access.sh \
  --host 0.0.0.0 \
  --generate-token \
  --cors http://192.168.1.20:3000
```

The configurator updates `/etc/jetson-yolo-webui.env`, sets permissions to `600`, and restarts the service.

## Service Operations

```bash
sudo systemctl status jetson-yolo-webui --no-pager
sudo systemctl restart jetson-yolo-webui
sudo systemctl status jetson-yolo-webui-healthcheck.timer --no-pager
sudo systemctl list-timers jetson-yolo-webui-healthcheck.timer --no-pager
sudo journalctl -u jetson-yolo-webui -n 100 --no-pager
tail -n 100 /opt/jetson-yolo-webui/runtime/healthcheck.log
```

Post-install verification:

```bash
BASE_URL=http://127.0.0.1:8765 \
  /opt/jetson-yolo-webui/current/webui/deploy/verify_deployment.sh
```

After enabling token auth with a root-readable env file, run:

```bash
sudo BASE_URL=http://127.0.0.1:8765 \
  /opt/jetson-yolo-webui/current/webui/deploy/verify_deployment.sh
```

## Rollback

Service rollback should be a symlink change or package reinstall, not a rebuild.

Recommended pattern:

```text
/opt/jetson-yolo-webui/releases/0.1.1/
/opt/jetson-yolo-webui/releases/0.2.0/
/opt/jetson-yolo-webui/current -> releases/0.2.0/
```

Keep the previous package until the new package survives smoke tests.

## GitHub Preparation

Before adding a GitHub remote:

- remove sensitive paths from examples
- keep secrets out of git history
- add a clear license if the repo will be shared
- decide whether benchmark reports are tracked or release artifacts only
- decide whether large engines/models go to Git LFS or external artifact storage
