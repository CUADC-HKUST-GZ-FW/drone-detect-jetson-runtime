from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib import request

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = Path(os.environ.get("PROJECT_DIR", "/workspace"))
HOST_PROJECT_DIR = os.environ.get("HOST_PROJECT_DIR", "/opt/drone-detect")
EXEC_MODE = os.environ.get("DRONE_EXEC_MODE", "local")
RUNNER_URL = os.environ.get("DRONE_RUNNER_URL", "http://127.0.0.1:18081").rstrip("/")
DEFAULT_INTERFACE = os.environ.get("DRONE_INTERFACE", "eth0")
NODE_ROLE = os.environ.get("NODE_ROLE", "standalone")
RESULTS_DIR = PROJECT_DIR / "results" / "webui"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Drone Detect WebUI")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


class CommandBody(BaseModel):
    command: str
    timeout: int = 120


class TcBody(BaseModel):
    config: str = "configs/degraded_policy.example.json"
    interface: str = DEFAULT_INTERFACE
    dst_ip: str | None = None
    backend: str | None = "simple"
    allow_ssh_interface: bool = True
    auto_rollback_seconds: int = 35


class YoloBody(BaseModel):
    model: str = "yolov26n"
    source: str = "assets/test_20s.mp4"
    max_frames: int = 5
    device: str = "0"


class StreamBody(BaseModel):
    role: str
    dest: str | None = None
    port: int = 5000
    duration: int = 20
    source: str = "testsrc"
    output: str = "results/webui/received.ts"


def now_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def rel(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def nsenter_prefix() -> list[str]:
    return [
        "nsenter",
        "--target",
        "1",
        "--mount",
        "--uts",
        "--ipc",
        "--net",
        "--pid",
        "--",
        "bash",
        "-lc",
    ]


def run_local(command: str, timeout: int = 120) -> dict[str, Any]:
    started = time.time()
    if EXEC_MODE == "nsenter":
        if command.strip().startswith("sudo "):
            host_command = command.strip()[5:]
            wrapped = f"cd {shlex.quote(HOST_PROJECT_DIR)} && {host_command}"
        else:
            user_command = f"cd {shlex.quote(HOST_PROJECT_DIR)} && {command}"
            host_user = os.environ.get("HOST_RUN_USER", "doit")
            wrapped = f"runuser -u {shlex.quote(host_user)} -- bash -lc " + shlex.quote(user_command)
        argv = nsenter_prefix() + [wrapped]
        shell = False
    else:
        wrapped = f"cd {shlex.quote(str(PROJECT_DIR))} && {command}"
        argv = wrapped
        shell = True
    proc = subprocess.run(
        argv,
        shell=shell,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    return {
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "elapsed_s": round(time.time() - started, 3),
    }


def proxy_json(path: str, method: str = "GET", data: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{RUNNER_URL}{path}"
    body = None if data is None else json.dumps(data).encode("utf-8")
    headers = {"Content-Type": "application/json"} if body else {}
    req = request.Request(url, data=body, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=180) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"runner request failed: {exc}") from exc


def execute(command: str, timeout: int = 120) -> dict[str, Any]:
    if EXEC_MODE == "proxy":
        return proxy_json("/api/run", "POST", {"command": command, "timeout": timeout})
    return run_local(command, timeout)


def list_results(limit: int = 80) -> list[dict[str, Any]]:
    root = PROJECT_DIR / "results"
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append({
            "path": rel(path.relative_to(PROJECT_DIR)),
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        })
    rows.sort(key=lambda x: x["mtime"], reverse=True)
    return rows[:limit]


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
def status() -> dict[str, Any]:
    if EXEC_MODE == "proxy":
        base = proxy_json("/api/status")
        base["webui"] = {"mode": EXEC_MODE, "runner": RUNNER_URL}
        return base

    checks = {
        "hostname": "hostname",
        "uptime": "uptime -p || true",
        "role": f"printf '%s\\n' {shlex.quote(NODE_ROLE)}",
        "docker": "docker --version 2>&1 || true; docker compose version 2>&1 || true",
        "gpu": ".venv/bin/python - <<'PY'\nimport torch\nprint('torch', torch.__version__)\nprint('cuda', torch.cuda.is_available())\nprint('cuda_version', torch.version.cuda)\nprint('device_count', torch.cuda.device_count())\nprint('device_name', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')\nPY",
        "tc": f"tc -s qdisc show dev {shlex.quote(DEFAULT_INTERFACE)} 2>&1 || true",
        "services": "docker ps --format '{{.Names}} {{.Status}}' 2>&1 || true",
    }
    out: dict[str, Any] = {"mode": EXEC_MODE, "project_dir": str(PROJECT_DIR), "host_project_dir": HOST_PROJECT_DIR}
    for key, cmd in checks.items():
        out[key] = run_local(cmd, timeout=30)
    return out


@app.post("/api/run")
def run_command(body: CommandBody) -> dict[str, Any]:
    return run_local(body.command, body.timeout)


@app.post("/api/tc/dry-run")
def tc_dry_run(body: TcBody) -> dict[str, Any]:
    cmd = ["python3", "scripts/tc_apply.py", "--config", body.config, "--dry-run"]
    if body.dst_ip:
        cmd.extend(["--set-dst-ip", body.dst_ip])
    if body.backend:
        cmd.extend(["--backend", body.backend])
    return execute(" ".join(shlex.quote(x) for x in cmd), timeout=60)


@app.post("/api/tc/apply")
def tc_apply(body: TcBody) -> dict[str, Any]:
    cmd = ["python3", "scripts/tc_apply.py", "--config", body.config, "--apply", "--yes"]
    if body.dst_ip:
        cmd.extend(["--set-dst-ip", body.dst_ip])
    if body.backend:
        cmd.extend(["--backend", body.backend])
    if body.allow_ssh_interface:
        cmd.append("--allow-ssh-interface")
    cmd.extend(["--auto-rollback-seconds", str(body.auto_rollback_seconds)])
    return execute("sudo " + " ".join(shlex.quote(x) for x in cmd), timeout=90)


@app.post("/api/tc/status")
def tc_status(body: TcBody) -> dict[str, Any]:
    cmd = f"python3 scripts/tc_apply.py --interface {shlex.quote(body.interface)} --status"
    return execute(cmd, timeout=60)


@app.post("/api/tc/clear")
def tc_clear(body: TcBody) -> dict[str, Any]:
    cmd = f"sudo python3 scripts/tc_apply.py --interface {shlex.quote(body.interface)} --clear --yes"
    return execute(cmd, timeout=60)


@app.post("/api/yolo/run")
def yolo_run(body: YoloBody) -> dict[str, Any]:
    out_dir = f"results/yolo/webui_{now_id()}"
    cmd = [
        ".venv/bin/python",
        "scripts/run_yolo_video.py",
        "--model",
        body.model,
        "--source",
        body.source,
        "--output-dir",
        out_dir,
        "--device",
        body.device,
        "--max-frames",
        str(body.max_frames),
    ]
    return execute(" ".join(shlex.quote(x) for x in cmd), timeout=300)


@app.post("/api/stream/start")
def stream_start(body: StreamBody) -> dict[str, Any]:
    run_id = now_id()
    log_path = f"results/webui/stream_{body.role}_{run_id}.log"
    if body.role == "receiver":
        cmd = [
            "bash",
            "scripts/start_receiver.sh",
            "--port",
            str(body.port),
            "--duration",
            str(body.duration),
            "--output",
            body.output,
        ]
    elif body.role == "sender":
        if not body.dest:
            raise HTTPException(status_code=400, detail="dest is required for sender")
        cmd = [
            "bash",
            "scripts/start_sender.sh",
            "--dest",
            body.dest,
            "--port",
            str(body.port),
            "--duration",
            str(body.duration),
            "--source",
            body.source,
        ]
    else:
        raise HTTPException(status_code=400, detail="role must be sender or receiver")
    command = f"mkdir -p results/webui && nohup {' '.join(shlex.quote(x) for x in cmd)} > {shlex.quote(log_path)} 2>&1 & echo $!"
    return execute(command, timeout=20)


@app.get("/api/results")
def results() -> dict[str, Any]:
    return {"results": list_results()}


@app.get("/api/log")
def log(path: str) -> PlainTextResponse:
    target = (PROJECT_DIR / path).resolve()
    if PROJECT_DIR.resolve() not in target.parents and target != PROJECT_DIR.resolve():
        raise HTTPException(status_code=400, detail="path outside project")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return PlainTextResponse(target.read_text(encoding="utf-8", errors="replace")[-20000:])


@app.exception_handler(subprocess.TimeoutExpired)
async def timeout_handler(_, exc: subprocess.TimeoutExpired) -> JSONResponse:
    return JSONResponse(status_code=504, content={"detail": f"command timed out after {exc.timeout}s"})


@app.on_event("startup")
async def startup() -> None:
    await asyncio.sleep(0)
