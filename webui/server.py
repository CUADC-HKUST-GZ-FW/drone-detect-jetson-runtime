#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import parse_qs, urlparse


APP_ROOT = Path(__file__).resolve().parent
DOCS_ROOT = Path(os.environ.get("JETSON_DOCS_ROOT", APP_ROOT.parent)).expanduser()
STATIC_ROOT = APP_ROOT / "static"
RUNTIME_ROOT = Path(os.environ.get("JETSON_WEBUI_RUNTIME_ROOT", str(APP_ROOT / "runtime"))).expanduser()
RUNS_ROOT = RUNTIME_ROOT / "runs"
DEFAULT_CONFIG_TEMPLATE = DOCS_ROOT / "templates" / "pipeline_config.example.yaml"
DEFAULT_RUNTIME_CONFIG = RUNTIME_ROOT / "pipeline_config.yaml"
VERSION_FILE = APP_ROOT / "version.json"

ASSET_ROOT = Path(os.environ.get("JETSON_ASSET_ROOT", "~/jetson_benchmark_assets")).expanduser()
RELEASE_ROOT = Path(os.environ.get("JETSON_RELEASE_ROOT", "/opt/yolo-pipeline/current")).expanduser()
PIPELINE_CONFIG = Path(
    os.environ.get("YOLO_PIPELINE_CONFIG", str(DEFAULT_RUNTIME_CONFIG))
).expanduser()
ACCESS_TOKEN = os.environ.get("JETSON_WEBUI_TOKEN", "")
CORS_ORIGINS = [x.strip() for x in os.environ.get("JETSON_WEBUI_CORS_ORIGIN", "").split(",") if x.strip()]
ALLOW_NO_AUTH_EXTERNAL = os.environ.get("JETSON_WEBUI_ALLOW_NO_AUTH_EXTERNAL", "0") == "1"
MAX_BODY_BYTES = int(os.environ.get("JETSON_WEBUI_MAX_BODY_BYTES", "1048576"))

RUNS: dict[str, dict] = {}
RUNS_LOCK = threading.Lock()
ACTION_DEFINITIONS = {
    "validate_config": {
        "description": "Validate the active pipeline config.",
        "params": {},
        "timeout_sec": 1,
    },
    "tegrastats_5s": {
        "description": "Capture a short tegrastats sample.",
        "params": {},
        "timeout_sec": 6,
    },
    "gst_hwdecode_smoke": {
        "description": "Validate H.264 hardware decode with nvv4l2decoder.",
        "params": {"video": "absolute readable video path"},
        "timeout_sec": 30,
    },
    "strict1024_cpp_smoke": {
        "description": "Run the strict 1024 C++ TensorRT smoke runner.",
        "params": {
            "video": "absolute readable video path",
            "runner": "optional absolute runner path under run roots",
            "engine": "optional absolute engine path under run roots",
            "warmup": "seconds",
            "measure": "seconds",
            "slots": "pipeline slots",
        },
        "timeout_sec": "warmup + measure + 90",
    },
    "cascade_cpp_smoke": {
        "description": "Run the two-stage cascade C++ TensorRT smoke runner.",
        "params": {
            "video": "absolute readable video path",
            "runner": "optional absolute runner path under run roots",
            "stage1_engine": "optional absolute engine path under run roots",
            "stage2_engine": "optional absolute engine path under run roots",
            "warmup": "seconds",
            "measure": "seconds",
            "slots": "pipeline slots",
        },
        "timeout_sec": "warmup + measure + 90",
    },
}
ALLOWLISTED_ACTIONS = list(ACTION_DEFINITIONS)


class ActionError(Exception):
    pass


class RequestTooLarge(Exception):
    pass


class FastThreadingHTTPServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_runtime() -> None:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    if not PIPELINE_CONFIG.exists() and DEFAULT_CONFIG_TEMPLATE.exists():
        PIPELINE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        PIPELINE_CONFIG.write_text(DEFAULT_CONFIG_TEMPLATE.read_text(), encoding="utf-8")


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return default


def load_version() -> dict:
    try:
        return json.loads(VERSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        version = read_text(DOCS_ROOT / "VERSION", "0.0.0").strip()
        return {"name": "jetson-yolo-pipeline-webui", "version": version, "api_version": "0.6"}


def is_loopback_host(host: str) -> bool:
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def enforce_auth_policy(host: str) -> None:
    if ACCESS_TOKEN or ALLOW_NO_AUTH_EXTERNAL or is_loopback_host(host):
        return
    raise SystemExit(
        "Refusing to bind WebUI to a non-loopback address without JETSON_WEBUI_TOKEN. "
        "Set JETSON_WEBUI_TOKEN or explicitly set JETSON_WEBUI_ALLOW_NO_AUTH_EXTERNAL=1."
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def command_path(name: str) -> str | None:
    return shutil.which(name)


def tail_file(path: Path, max_bytes: int = 65536) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return f"[tail failed] {exc}"


def sha_hint(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return f"{path.stat().st_size} bytes"
    except Exception:
        return None


def list_files(root: Path, patterns: tuple[str, ...], limit: int = 200) -> list[dict]:
    items: list[dict] = []
    if not root.exists():
        return items
    for pattern in patterns:
        for p in sorted(root.rglob(pattern)):
            if len(items) >= limit:
                return items
            if p.is_file():
                try:
                    items.append(
                        {
                            "path": str(p),
                            "name": p.name,
                            "bytes": p.stat().st_size,
                            "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                        }
                    )
                except Exception:
                    items.append({"path": str(p), "name": p.name})
    return items


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        resolved = path.expanduser().resolve(strict=False)
        key = str(resolved)
        if key not in seen:
            result.append(resolved)
            seen.add(key)
    return result


def configured_extra_roots(env_name: str) -> list[Path]:
    raw = os.environ.get(env_name, "")
    return [Path(item).expanduser() for item in raw.split(os.pathsep) if item.strip()]


def readable_roots() -> list[Path]:
    return unique_paths([ASSET_ROOT, RELEASE_ROOT, RUNTIME_ROOT, RUNS_ROOT] + configured_extra_roots("JETSON_WEBUI_READ_ROOTS"))


def operator_homes() -> list[Path]:
    homes = [Path.home()]
    asset_parent = ASSET_ROOT.expanduser().resolve(strict=False).parent
    if asset_parent.name and asset_parent.parent == Path("/home"):
        homes.append(asset_parent)
    release_parent = RELEASE_ROOT.expanduser().resolve(strict=False).parent
    if release_parent.name and release_parent.parent == Path("/home"):
        homes.append(release_parent)
    return unique_paths(homes)


def benchmark_roots() -> list[Path]:
    roots: list[Path] = []
    for home in operator_homes():
        roots.extend(
            [
                home / "jetson_90fps_yolo26n1024",
                home / "jetson_cascade_benchmark",
            ]
        )
    return unique_paths(roots)


def first_existing_or_default(paths: list[Path]) -> Path:
    for path in paths:
        if path.exists():
            return path
    return paths[0]


def strict1024_runner_path() -> Path:
    return first_existing_or_default([root / "scripts" / "native_trt_video_strict_square_runner" for root in benchmark_roots()])


def strict1024_engine_path() -> Path:
    return first_existing_or_default([root / "engines" / "yolo26n_1024_fp16.raw.engine" for root in benchmark_roots()])


def cascade_runner_path() -> Path:
    return first_existing_or_default([root / "scripts" / "cascade_trt_pipeline_runner" for root in benchmark_roots()])


def cascade_stage1_path() -> Path:
    return first_existing_or_default([root / "engines" / "yolo26n_1024_fp16.raw.engine" for root in benchmark_roots()])


def cascade_stage2_path() -> Path:
    return first_existing_or_default([root / "engines" / "yolo26n_requested400_actual416_fp16.raw.engine" for root in benchmark_roots()])


def runnable_roots() -> list[Path]:
    return unique_paths(
        [
            ASSET_ROOT,
            RELEASE_ROOT,
            RUNS_ROOT,
        ]
        + benchmark_roots()
        + configured_extra_roots("JETSON_WEBUI_RUN_ROOTS")
    )


def path_is_under(path: Path, roots: list[Path]) -> bool:
    resolved = path.expanduser().resolve(strict=False)
    for root in roots:
        try:
            resolved.relative_to(root.expanduser().resolve(strict=False))
            return True
        except ValueError:
            continue
    return False


def validate_user_path(raw: object, *, label: str, roots: list[Path]) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ActionError(f"{label} path is required")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ActionError(f"{label} path must be absolute")
    resolved = path.resolve(strict=False)
    if not path_is_under(resolved, roots):
        allowed = ", ".join(str(root) for root in roots)
        raise ActionError(f"{label} path is outside allowed roots: {allowed}")
    return resolved


def readable_file_allowed(path: Path) -> bool:
    return path_is_under(path, readable_roots())


def validate_config_text(text: str) -> dict:
    warnings: list[str] = []
    errors: list[str] = []

    required_tokens = [
        "release_id:",
        "strict_resolution:",
        "requested_imgsz:",
        "actual_imgsz:",
        "engine:",
        "letterbox_value:",
    ]
    for token in required_tokens:
        if token not in text:
            errors.append(f"missing token: {token}")

    if "1024" in text and "strict_resolution: true" not in text:
        warnings.append("1024 appears in config, but strict_resolution: true was not found.")

    if "[400, 400]" in text and "[416, 416]" not in text:
        warnings.append("requested 400 appears without actual 416. Check YOLO stride adjustment.")

    if "per_frame_stdout: true" in text:
        warnings.append("per-frame stdout is enabled; this can reduce wall FPS.")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def pick_asset(items: list[dict], preferences: list[tuple[str, ...]]) -> dict | None:
    for terms in preferences:
        for item in items:
            name = str(item.get("name", "")).lower()
            path = str(item.get("path", "")).lower()
            haystack = f"{name} {path}"
            if all(term in haystack for term in terms):
                return item
    return items[0] if items else None


def selected_defaults(assets: dict) -> dict:
    video = pick_asset(
        assets.get("videos", []),
        [
            ("1080p", "coco_val2017"),
            ("1080p", "val2017"),
            ("1080p", "coco"),
            ("1080p",),
            ("720p", "coco_val2017"),
            ("720p", "val2017"),
            ("720p", "coco"),
            ("720p",),
            (".mp4",),
        ],
    )
    stage1_engine = pick_asset(
        assets.get("engines", []),
        [
            ("yolo26n", "1024", "fp16"),
            ("1024", "fp16"),
            ("yolo26n", "640", "int8"),
            ("640", "int8"),
        ],
    )
    stage2_engine = pick_asset(
        assets.get("engines", []),
        [
            ("416", "fp16"),
            ("400", "fp16"),
            ("416",),
            ("400",),
        ],
    )
    model = pick_asset(
        assets.get("models", []),
        [
            ("yolo26n",),
            ("yolo11n",),
            (".pt",),
        ],
    )
    return {
        "video": video,
        "stage1_engine": stage1_engine,
        "stage2_engine": stage2_engine,
        "model": model,
    }


def replace_yaml_scalar(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^(\s*{re.escape(key)}:\s*).*$", re.MULTILINE)
    return pattern.sub(lambda match: match.group(1) + value, text, count=1)


def generate_config_from_template(defaults: dict) -> str:
    text = read_text(DEFAULT_CONFIG_TEMPLATE)
    if not text:
        text = read_text(PIPELINE_CONFIG)

    video = defaults.get("video") or {}
    stage1 = defaults.get("stage1_engine") or {}
    stage2 = defaults.get("stage2_engine") or {}

    text = replace_yaml_scalar(text, "release_root", str(RELEASE_ROOT))
    if video.get("path"):
        text = replace_yaml_scalar(text, "uri", str(video["path"]))
    if stage1.get("path"):
        text = text.replace(
            "engine: /opt/yolo-pipeline/current/engines/yolo26n_1024_fp16.raw.engine",
            f"engine: {stage1['path']}",
            1,
        )
    if stage2.get("path"):
        text = text.replace(
            "engine: /opt/yolo-pipeline/current/engines/yolo26n_requested400_actual416_fp16.raw.engine",
            f"engine: {stage2['path']}",
            1,
        )
    return text


def readiness_checks(assets: dict, defaults: dict) -> list[dict]:
    config_text = read_text(PIPELINE_CONFIG)
    validation = validate_config_text(config_text)

    def check(item_id: str, ok: bool, label: str, detail: str, severity: str = "blocker") -> dict:
        return {
            "id": item_id,
            "ok": bool(ok),
            "label": label,
            "detail": detail,
            "severity": severity,
        }

    return [
        check("config_valid", validation["ok"], "Config", str(PIPELINE_CONFIG)),
        check("runtime_writable", os.access(RUNTIME_ROOT, os.W_OK), "Runtime writable", str(RUNTIME_ROOT)),
        check("video_available", bool(defaults.get("video")), "Video source", str((defaults.get("video") or {}).get("path", ""))),
        check("engine_available", bool(defaults.get("stage1_engine")), "TensorRT engine", str((defaults.get("stage1_engine") or {}).get("path", ""))),
        check("tegrastats_available", command_exists("tegrastats"), "tegrastats", command_path("tegrastats") or "missing", "warning"),
        check("gstreamer_available", command_exists("gst-launch-1.0"), "GStreamer", command_path("gst-launch-1.0") or "missing", "warning"),
        check("external_auth", bool(ACCESS_TOKEN), "External API token", "configured" if ACCESS_TOKEN else "not configured; loopback-only mode is safest", "warning"),
        check("action_roots", bool(runnable_roots()), "Action roots", ", ".join(str(root) for root in runnable_roots()), "warning"),
        check("models_available", bool(assets.get("models")), "Model weights", f"{len(assets.get('models', []))} found", "warning"),
    ]


def bootstrap_payload() -> dict:
    assets = assets_payload()
    defaults = selected_defaults(assets)
    checks = readiness_checks(assets, defaults)
    blockers = [item for item in checks if not item["ok"] and item["severity"] == "blocker"]
    config_text = read_text(PIPELINE_CONFIG)
    return {
        "ok": not blockers,
        "time": utc_now(),
        "asset_counts": {
            "models": len(assets.get("models", [])),
            "engines": len(assets.get("engines", [])),
            "videos": len(assets.get("videos", [])),
            "logs": len(assets.get("logs", [])),
            "reports": len(assets.get("reports", [])),
        },
        "selected_defaults": defaults,
        "config": {
            "path": str(PIPELINE_CONFIG),
            "exists": PIPELINE_CONFIG.exists(),
            "validation": validate_config_text(config_text),
            "template": str(DEFAULT_CONFIG_TEMPLATE),
        },
        "readiness": checks,
        "security": {
            "auth_required": bool(ACCESS_TOKEN),
            "cors_origins": CORS_ORIGINS,
            "read_roots": [str(root) for root in readable_roots()],
            "run_roots": [str(root) for root in runnable_roots()],
            "allowlisted_actions": ALLOWLISTED_ACTIONS,
        },
    }


def initialize_config(*, write_config: bool = True, force: bool = False) -> dict:
    assets = assets_payload()
    defaults = selected_defaults(assets)
    generated = generate_config_from_template(defaults)
    validation = validate_config_text(generated)
    current = read_text(PIPELINE_CONFIG)
    current_validation = validate_config_text(current)
    should_write = force or not PIPELINE_CONFIG.exists() or not current_validation["ok"]
    changed = bool(write_config and should_write)
    if changed:
        write_text(PIPELINE_CONFIG, generated)
    return {
        "ok": validation["ok"],
        "changed": changed,
        "path": str(PIPELINE_CONFIG),
        "selected_defaults": defaults,
        "validation": validation,
        "text": generated,
    }


def actions_payload() -> dict:
    return {
        "actions": ACTION_DEFINITIONS,
        "read_roots": [str(root) for root in readable_roots()],
        "run_roots": [str(root) for root in runnable_roots()],
        "defaults": {
            "strict1024_runner": str(strict1024_runner_path()),
            "strict1024_engine": str(strict1024_engine_path()),
            "cascade_runner": str(cascade_runner_path()),
            "cascade_stage1_engine": str(cascade_stage1_path()),
            "cascade_stage2_engine": str(cascade_stage2_path()),
        },
    }


def fixed_command(cmd: list[str], timeout: float = 2.0) -> dict:
    try:
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "output": (proc.stdout or "").strip()[:2000],
        }
    except FileNotFoundError:
        return {"ok": False, "exit_code": 127, "output": "command not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": None, "output": "timeout"}
    except Exception as exc:
        return {"ok": False, "exit_code": 1, "output": repr(exc)}


def path_state(path: Path) -> dict:
    expanded = path.expanduser().resolve(strict=False)
    return {
        "path": str(expanded),
        "exists": expanded.exists(),
        "is_file": expanded.is_file(),
        "is_dir": expanded.is_dir(),
        "readable": os.access(expanded, os.R_OK),
        "writable": os.access(expanded, os.W_OK),
    }


def disk_state(path: Path) -> dict:
    target = path if path.exists() else path.parent
    try:
        usage = shutil.disk_usage(target)
        return {
            "path": str(path.expanduser().resolve(strict=False)),
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
        }
    except Exception as exc:
        return {"path": str(path), "error": repr(exc)}


def systemd_unit_state(unit: str) -> dict:
    if not command_exists("systemctl"):
        return {"available": False, "active": None, "enabled": None}
    active = fixed_command(["systemctl", "is-active", unit], timeout=2)
    enabled = fixed_command(["systemctl", "is-enabled", unit], timeout=2)
    return {
        "available": True,
        "active": active.get("output"),
        "enabled": enabled.get("output"),
        "active_ok": active["ok"],
        "enabled_ok": enabled["ok"],
    }


def diagnostics_payload() -> dict:
    bootstrap = bootstrap_payload()
    health = health_payload()
    return {
        "ok": health["ok"],
        "time": utc_now(),
        "version": load_version(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "health": health,
        "bootstrap_ok": bootstrap["ok"],
        "asset_counts": bootstrap["asset_counts"],
        "paths": {
            "docs_root": path_state(DOCS_ROOT),
            "asset_root": path_state(ASSET_ROOT),
            "release_root": path_state(RELEASE_ROOT),
            "runtime_root": path_state(RUNTIME_ROOT),
            "runs_root": path_state(RUNS_ROOT),
            "pipeline_config": path_state(PIPELINE_CONFIG),
        },
        "disk": {
            "runtime_root": disk_state(RUNTIME_ROOT),
            "asset_root": disk_state(ASSET_ROOT),
        },
        "commands": {
            name: {"available": command_exists(name), "path": command_path(name)}
            for name in ["python3", "tegrastats", "gst-launch-1.0", "gst-inspect-1.0", "curl", "systemctl"]
        },
        "systemd": {
            "webui_service": systemd_unit_state("jetson-yolo-webui.service"),
            "healthcheck_timer": systemd_unit_state("jetson-yolo-webui-healthcheck.timer"),
        },
        "security": {
            "auth_required": bool(ACCESS_TOKEN),
            "cors_origins": CORS_ORIGINS,
            "allow_no_auth_external": ALLOW_NO_AUTH_EXTERNAL,
            "max_body_bytes": MAX_BODY_BYTES,
            "read_roots": [str(root) for root in readable_roots()],
            "run_roots": [str(root) for root in runnable_roots()],
        },
    }


def health_payload() -> dict:
    config_text = read_text(PIPELINE_CONFIG)
    validation = validate_config_text(config_text)
    return {
        "ok": validation["ok"],
        "time": utc_now(),
        "version": load_version(),
        "config_path": str(PIPELINE_CONFIG),
        "config_validation": validation,
        "runtime_root_writable": os.access(RUNTIME_ROOT, os.W_OK),
    }


def auth_payload() -> dict:
    return {
        "auth_required": bool(ACCESS_TOKEN),
        "methods": ["X-Auth-Token", "Authorization: Bearer"],
        "query_token_supported": False,
        "health_requires_auth": False,
        "external_bind_requires_token": True,
        "cors_origins": CORS_ORIGINS,
    }


def openapi_payload() -> dict:
    version = load_version()
    security = [{"ApiToken": []}]
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Jetson YOLO Pipeline WebUI API",
            "version": version.get("api_version", "0.1"),
            "description": "Local management API for Jetson YOLO TensorRT/GStreamer pipeline setup and smoke tests.",
        },
        "servers": [{"url": "/"}],
        "components": {
            "securitySchemes": {
                "ApiToken": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Auth-Token",
                    "description": "Same value as JETSON_WEBUI_TOKEN. Authorization: Bearer <token> is also accepted.",
                }
            }
        },
        "paths": {
            "/api/health": {"get": {"summary": "Unauthenticated healthcheck", "responses": {"200": {"description": "Health payload"}}}},
            "/api/auth": {"get": {"summary": "Unauthenticated auth metadata", "responses": {"200": {"description": "Auth metadata"}}}},
            "/api/status": {"get": {"summary": "Runtime status", "security": security, "responses": {"200": {"description": "Status payload"}}}},
            "/api/version": {"get": {"summary": "Service version", "security": security, "responses": {"200": {"description": "Version payload"}}}},
            "/api/assets": {"get": {"summary": "List known assets", "security": security, "responses": {"200": {"description": "Assets payload"}}}},
            "/api/actions": {"get": {"summary": "List allowlisted actions and parameter hints", "security": security, "responses": {"200": {"description": "Actions payload"}}}},
            "/api/diagnostics": {"get": {"summary": "Deployment diagnostics with redacted security state", "security": security, "responses": {"200": {"description": "Diagnostics payload"}}}},
            "/api/bootstrap": {
                "get": {"summary": "Read first-run readiness and selected defaults", "security": security, "responses": {"200": {"description": "Bootstrap payload"}}},
                "post": {"summary": "Initialize or repair pipeline config from discovered assets", "security": security, "responses": {"200": {"description": "Bootstrap result"}}},
            },
            "/api/config": {
                "get": {"summary": "Read pipeline config", "security": security, "responses": {"200": {"description": "Config payload"}}},
                "post": {"summary": "Write pipeline config", "security": security, "responses": {"200": {"description": "Validation payload"}}},
            },
            "/api/run": {"post": {"summary": "Start allowlisted action", "security": security, "responses": {"200": {"description": "Run record"}}}},
            "/api/runs": {"get": {"summary": "List recent runs", "security": security, "responses": {"200": {"description": "Run list"}}}},
            "/api/runs/{run_id}": {"get": {"summary": "Get run status and log tail", "security": security, "responses": {"200": {"description": "Run record"}}}},
            "/api/log": {"get": {"summary": "Tail selected log path", "security": security, "responses": {"200": {"description": "Log tail"}}}},
            "/api/openapi.json": {"get": {"summary": "OpenAPI specification", "security": security, "responses": {"200": {"description": "OpenAPI JSON"}}}},
        },
    }


def status_payload() -> dict:
    nv_tegra = Path("/etc/nv_tegra_release")
    return {
        "time": utc_now(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "version": load_version(),
        "is_jetson": nv_tegra.exists(),
        "l4t": read_text(nv_tegra).strip() if nv_tegra.exists() else None,
        "paths": {
            "docs_root": str(DOCS_ROOT),
            "asset_root": str(ASSET_ROOT),
            "release_root": str(RELEASE_ROOT),
            "pipeline_config": str(PIPELINE_CONFIG),
            "runtime_root": str(RUNTIME_ROOT),
        },
        "commands": {
            "tegrastats": command_exists("tegrastats"),
            "gst-launch-1.0": command_exists("gst-launch-1.0"),
            "gst-inspect-1.0": command_exists("gst-inspect-1.0"),
            "python3": command_exists("python3"),
        },
        "auth_required": bool(ACCESS_TOKEN),
        "known_results": {
            "strict_1024_single_cpp_fps": 103.0,
            "cascade_800_requested400_actual416_fps": 113.0,
            "cascade_1024_requested400_actual416_fps": 87.5,
        },
    }


def assets_payload() -> dict:
    roots = [ASSET_ROOT, RELEASE_ROOT] + benchmark_roots() + [RUNTIME_ROOT, RUNS_ROOT]
    unique_roots = []
    for root in roots:
        if root not in unique_roots:
            unique_roots.append(root)
    models: list[dict] = []
    engines: list[dict] = []
    videos: list[dict] = []
    logs: list[dict] = []
    reports: list[dict] = []
    for root in unique_roots:
        models.extend(list_files(root, ("*.pt",), limit=80))
        engines.extend(list_files(root, ("*.engine", "*.raw.engine"), limit=160))
        videos.extend(list_files(root, ("*.mp4", "*.mkv", "*.avi"), limit=120))
        logs.extend(list_files(root, ("*.log", "*.stderr"), limit=120))
        reports.extend(list_files(root, ("*.md", "*.json", "*.csv"), limit=160))
    return {
        "models": models[:120],
        "engines": engines[:200],
        "videos": videos[:160],
        "logs": logs[:160],
        "reports": reports[:200],
    }


def make_run_record(action: str, params: dict) -> dict:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    return {
        "id": run_id,
        "action": action,
        "params": params,
        "created_at": utc_now(),
        "started_at": None,
        "finished_at": None,
        "status": "queued",
        "exit_code": None,
        "log_path": str(RUNS_ROOT / f"{run_id}.log"),
        "record_path": str(RUNS_ROOT / f"{run_id}.json"),
    }


def save_run(record: dict) -> None:
    write_text(Path(record["record_path"]), json.dumps(record, indent=2),)


def run_completed_action(record: dict, payload: dict) -> dict:
    record["started_at"] = utc_now()
    record["finished_at"] = utc_now()
    record["status"] = "succeeded" if payload.get("ok", False) else "failed"
    record["exit_code"] = 0 if payload.get("ok", False) else 2
    write_text(Path(record["log_path"]), json.dumps(payload, indent=2) + "\n")
    save_run(record)
    return record


def clamp_int(value: object, default: int, low: int, high: int) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(low, min(high, n))


def action_command(action: str, params: dict) -> tuple[list[str], int] | None:
    video = str(
        validate_user_path(
            params.get("video") or str(ASSET_ROOT / "videos" / "benchmark_5min_1080p30_coco_val2017_synthetic.mp4"),
            label="video",
            roots=readable_roots(),
        )
    )
    warmup_n = clamp_int(params.get("warmup", 5), 5, 0, 300)
    measure_n = clamp_int(params.get("measure", 30), 30, 1, 1800)
    slots_n = clamp_int(params.get("slots", 4), 4, 1, 16)
    warmup = str(warmup_n)
    measure = str(measure_n)
    slots = str(slots_n)
    benchmark_timeout = warmup_n + measure_n + 90

    if action == "tegrastats_5s":
        return ["tegrastats"], 6

    if action == "gst_hwdecode_smoke":
        return [
            "gst-launch-1.0",
            "-q",
            "filesrc",
            f"location={video}",
            "!",
            "qtdemux",
            "!",
            "h264parse",
            "!",
            "nvv4l2decoder",
            "enable-max-performance=1",
            "!",
            "fakesink",
            "sync=false",
        ], 30

    if action == "strict1024_cpp_smoke":
        runner = str(
            validate_user_path(
                params.get("runner") or str(strict1024_runner_path()),
                label="runner",
                roots=runnable_roots(),
            )
        )
        engine = str(
            validate_user_path(
                params.get("engine") or str(strict1024_engine_path()),
                label="engine",
                roots=runnable_roots(),
            )
        )
        return [runner, engine, video, warmup, measure, "1024", slots, "1024", "576"], benchmark_timeout

    if action == "cascade_cpp_smoke":
        runner = str(
            validate_user_path(
                params.get("runner") or str(cascade_runner_path()),
                label="runner",
                roots=runnable_roots(),
            )
        )
        stage1 = str(
            validate_user_path(
                params.get("stage1_engine") or str(cascade_stage1_path()),
                label="stage1_engine",
                roots=runnable_roots(),
            )
        )
        stage2 = str(
            validate_user_path(
                params.get("stage2_engine") or str(cascade_stage2_path()),
                label="stage2_engine",
                roots=runnable_roots(),
            )
        )
        return [runner, stage1, stage2, video, "1024", "416", warmup, measure, slots, slots], benchmark_timeout

    return None


def execute_command_run(record: dict, cmd: list[str]) -> None:
    log_path = Path(record["log_path"])
    record["started_at"] = utc_now()
    record["status"] = "running"
    record["command"] = cmd
    save_run(record)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"$ {' '.join(cmd)}\n\n")
        log.flush()
        proc = None
        timer = None
        timed_out = False

        def kill_proc() -> None:
            nonlocal timed_out
            timed_out = True
            if proc and proc.poll() is None:
                proc.kill()

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            timer = threading.Timer(int(record.get("timeout_sec") or 300), kill_proc)
            timer.start()
            assert proc.stdout is not None
            for line in proc.stdout:
                log.write(line)
                log.flush()
            rc = proc.wait()
            record["exit_code"] = rc
            record["status"] = "timeout" if timed_out else ("succeeded" if rc == 0 else "failed")
        except FileNotFoundError as exc:
            log.write(f"[ERROR] command not found: {exc}\n")
            record["exit_code"] = 127
            record["status"] = "failed"
        except Exception as exc:
            log.write(f"[ERROR] command failed: {exc}\n")
            record["exit_code"] = 1
            record["status"] = "failed"
        finally:
            if timer:
                timer.cancel()
            record["finished_at"] = utc_now()
            save_run(record)


def start_action(action: str, params: dict) -> dict:
    record = make_run_record(action, params)
    with RUNS_LOCK:
        RUNS[record["id"]] = record

    if action == "validate_config":
        text = read_text(PIPELINE_CONFIG)
        result = validate_config_text(text)
        return run_completed_action(record, result)

    try:
        command_spec = action_command(action, params)
    except ActionError as exc:
        return run_completed_action(record, {"ok": False, "errors": [str(exc)]})
    if command_spec is None:
        return run_completed_action(record, {"ok": False, "errors": [f"unknown action: {action}"]})
    cmd, timeout_sec = command_spec
    record["timeout_sec"] = timeout_sec

    thread = threading.Thread(target=execute_command_run, args=(record, cmd), daemon=True)
    thread.start()
    save_run(record)
    return record


def load_persisted_runs() -> None:
    if not RUNS_ROOT.exists():
        return
    for p in sorted(RUNS_ROOT.glob("*.json"))[-100:]:
        try:
            record = json.loads(p.read_text(encoding="utf-8"))
            RUNS[record["id"]] = record
        except Exception:
            continue


class Handler(BaseHTTPRequestHandler):
    server_version = "JetsonYoloWebUI/0.6"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{utc_now()}] {self.address_string()} {fmt % args}")

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_common_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_common_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
            "style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        origin = self.headers.get("Origin", "")
        if CORS_ORIGINS:
            if "*" in CORS_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", "*")
            elif origin and origin in CORS_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Auth-Token, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, OPTIONS")

    def require_auth(self) -> bool:
        if not ACCESS_TOKEN:
            return True
        header = self.headers.get("Authorization", "")
        token_header = self.headers.get("X-Auth-Token", "")
        bearer = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
        valid = (
            (bearer and hmac.compare_digest(bearer, ACCESS_TOKEN))
            or (token_header and hmac.compare_digest(token_header, ACCESS_TOKEN))
        )
        if not valid:
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("WWW-Authenticate", "Bearer")
            self.send_common_headers()
            body = b'{\n  "error": "authentication required"\n}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        return valid

    def send_text(self, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_common_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_empty(self, status: int = 200, content_type: str = "text/plain; charset=utf-8", length: int = 0) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_common_headers()
        self.end_headers()

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise RequestTooLarge(f"request body too large: {length} > {MAX_BODY_BYTES}")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/api/health":
            self.send_json(health_payload())
            return

        if path == "/api/auth":
            self.send_json(auth_payload())
            return

        if path.startswith("/api/") and not self.require_auth():
            return

        if path == "/api/status":
            self.send_json(status_payload())
            return

        if path == "/api/version":
            self.send_json(load_version())
            return

        if path == "/api/openapi.json":
            self.send_json(openapi_payload())
            return

        if path == "/api/assets":
            self.send_json(assets_payload())
            return

        if path == "/api/actions":
            self.send_json(actions_payload())
            return

        if path == "/api/diagnostics":
            self.send_json(diagnostics_payload())
            return

        if path == "/api/bootstrap":
            self.send_json(bootstrap_payload())
            return

        if path == "/api/config":
            text = read_text(PIPELINE_CONFIG)
            self.send_json({"path": str(PIPELINE_CONFIG), "text": text, "validation": validate_config_text(text)})
            return

        if path == "/api/runs":
            with RUNS_LOCK:
                runs = sorted(RUNS.values(), key=lambda r: r.get("created_at", ""), reverse=True)
            self.send_json({"runs": runs[:100]})
            return

        if path.startswith("/api/runs/"):
            run_id = path.rsplit("/", 1)[-1]
            with RUNS_LOCK:
                record = RUNS.get(run_id)
            if not record:
                self.send_json({"error": "run not found"}, HTTPStatus.NOT_FOUND)
                return
            payload = dict(record)
            payload["log_tail"] = tail_file(Path(record["log_path"]))
            self.send_json(payload)
            return

        if path == "/api/log":
            raw_path = qs.get("path", [""])[0]
            p = Path(raw_path).expanduser()
            if raw_path and not readable_file_allowed(p):
                self.send_json({"error": "log path outside allowed roots"}, HTTPStatus.FORBIDDEN)
                return
            if not raw_path or not p.exists() or not p.is_file():
                self.send_json({"error": "log path not found"}, HTTPStatus.NOT_FOUND)
                return
            self.send_json({"path": str(p), "tail": tail_file(p)})
            return

        if path == "/" or path == "/index.html":
            self.serve_static("index.html")
            return

        if path.startswith("/static/"):
            self.serve_static(path[len("/static/") :])
            return

        self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/", "/index.html"}:
            p = STATIC_ROOT / "index.html"
            self.send_empty(HTTPStatus.OK, "text/html; charset=utf-8", p.stat().st_size if p.exists() else 0)
            return
        if path == "/api/health":
            body = json.dumps(health_payload(), indent=2).encode("utf-8")
            self.send_empty(HTTPStatus.OK, "application/json; charset=utf-8", len(body))
            return
        self.send_empty(HTTPStatus.NOT_FOUND)

    def do_OPTIONS(self) -> None:
        self.send_empty(HTTPStatus.NO_CONTENT)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/") and not self.require_auth():
            return

        try:
            payload = self.read_json_body()
        except RequestTooLarge as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        except Exception as exc:
            self.send_json({"error": f"invalid json: {exc}"}, HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/config":
            text = payload.get("text")
            if not isinstance(text, str):
                self.send_json({"error": "text is required"}, HTTPStatus.BAD_REQUEST)
                return
            write_text(PIPELINE_CONFIG, text)
            self.send_json({"ok": True, "path": str(PIPELINE_CONFIG), "validation": validate_config_text(text)})
            return

        if path == "/api/bootstrap":
            force = bool(payload.get("force", False))
            write_config = bool(payload.get("write_config", True))
            result = initialize_config(write_config=write_config, force=force)
            self.send_json(result)
            return

        if path == "/api/run":
            action = payload.get("action")
            params = payload.get("params", {})
            if not isinstance(action, str):
                self.send_json({"error": "action is required"}, HTTPStatus.BAD_REQUEST)
                return
            if not isinstance(params, dict):
                self.send_json({"error": "params must be an object"}, HTTPStatus.BAD_REQUEST)
                return
            record = start_action(action, params)
            self.send_json(record)
            return

        self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def serve_static(self, name: str) -> None:
        safe = Path(name)
        if safe.is_absolute() or ".." in safe.parts:
            self.send_json({"error": "bad path"}, HTTPStatus.BAD_REQUEST)
            return
        p = STATIC_ROOT / safe
        if not p.exists() or not p.is_file():
            self.send_json({"error": "static file not found"}, HTTPStatus.NOT_FOUND)
            return
        suffix = p.suffix.lower()
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(suffix, "application/octet-stream")
        self.send_text(p.read_text(encoding="utf-8"), content_type=content_type)


def main() -> None:
    parser = argparse.ArgumentParser(description="Jetson YOLO lightweight WebUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    ensure_runtime()
    enforce_auth_policy(args.host)
    load_persisted_runs()
    server = FastThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Jetson YOLO WebUI listening on http://{args.host}:{args.port}")
    print(f"Config path: {PIPELINE_CONFIG}")
    server.serve_forever()


if __name__ == "__main__":
    main()
