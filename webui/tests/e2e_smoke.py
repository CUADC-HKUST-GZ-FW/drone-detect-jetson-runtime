#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEBUI = ROOT / "webui"
SERVER = WEBUI / "server.py"
VERIFY_DEPLOYMENT = WEBUI / "deploy" / "verify_deployment.sh"
CONFIGURE_ACCESS = WEBUI / "deploy" / "configure_access.sh"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def request_json(url: str, method: str = "GET", data: object | None = None, headers: dict | None = None) -> tuple[int, dict]:
    body = None
    req_headers = dict(headers or {})
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        finally:
            exc.close()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"error": raw}
        return exc.code, payload


def request_text(url: str, headers: dict | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read().decode("utf-8", errors="replace")
        finally:
            exc.close()


class WebUIServer:
    def __init__(self, *, token: str = "", cors: str = "", max_body: int = 1048576, host: str = "127.0.0.1"):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.host = host
        env = os.environ.copy()
        env.update(
            {
                "PYTHONUNBUFFERED": "1",
                "JETSON_DOCS_ROOT": str(ROOT),
                "JETSON_ASSET_ROOT": str(self.tmp_path / "assets"),
                "JETSON_RELEASE_ROOT": str(self.tmp_path / "release"),
                "JETSON_WEBUI_RUNTIME_ROOT": str(self.tmp_path / "runtime"),
                "YOLO_PIPELINE_CONFIG": str(self.tmp_path / "runtime" / "pipeline_config.yaml"),
                "JETSON_WEBUI_TOKEN": token,
                "JETSON_WEBUI_CORS_ORIGIN": cors,
                "JETSON_WEBUI_MAX_BODY_BYTES": str(max_body),
            }
        )
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER), "--host", host, "--port", str(self.port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )

    def wait(self, expect_ready: bool = True) -> str:
        deadline = time.time() + 8
        output = []
        while time.time() < deadline:
            if self.proc.poll() is not None:
                if self.proc.stdout:
                    output.append(self.proc.stdout.read() or "")
                break
            if expect_ready:
                try:
                    status, payload = request_json(self.base + "/api/health")
                    if status == 200 and "ok" in payload:
                        return "".join(output)
                except Exception:
                    pass
            time.sleep(0.1)
        if expect_ready:
            self.stop()
            raise AssertionError("server did not become ready")
        return "".join(output)

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)
        if self.proc.stdout:
            self.proc.stdout.close()
        self.tmp.cleanup()

    def write_asset(self, relative: str, content: str = "test") -> Path:
        path = self.tmp_path / "assets" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path


class WebUISmokeTest(unittest.TestCase):
    def test_local_no_auth_workflow(self) -> None:
        srv = WebUIServer()
        try:
            srv.wait()
            status, health = request_json(srv.base + "/api/health")
            self.assertEqual(status, 200)
            self.assertTrue(health["ok"])

            status, page = request_text(srv.base + "/")
            self.assertEqual(status, 200)
            self.assertIn("Pipeline Management", page)
            self.assertIn("External API", page)
            self.assertIn("Set Token", page)

            status, openapi = request_json(srv.base + "/api/openapi.json")
            self.assertEqual(status, 200)
            self.assertEqual(openapi["openapi"], "3.1.0")
            self.assertIn("/api/auth", openapi["paths"])
            self.assertIn("/api/bootstrap", openapi["paths"])
            self.assertIn("/api/actions", openapi["paths"])
            self.assertIn("/api/diagnostics", openapi["paths"])

            status, auth = request_json(srv.base + "/api/auth")
            self.assertEqual(status, 200)
            self.assertFalse(auth["auth_required"])
            self.assertFalse(auth["query_token_supported"])

            video = srv.write_asset("videos/benchmark_5min_1080p30_coco_val2017_synthetic.mp4")
            stage1 = srv.write_asset("engines/yolo26n_1024_fp16.raw.engine")
            stage2 = srv.write_asset("engines/yolo26n_requested400_actual416_fp16.raw.engine")

            status, bootstrap = request_json(srv.base + "/api/bootstrap")
            self.assertEqual(status, 200)
            self.assertEqual(bootstrap["asset_counts"]["videos"], 1)
            self.assertEqual(bootstrap["selected_defaults"]["video"]["path"], str(video))
            self.assertEqual(bootstrap["selected_defaults"]["stage1_engine"]["path"], str(stage1))
            self.assertEqual(bootstrap["selected_defaults"]["stage2_engine"]["path"], str(stage2))

            status, actions = request_json(srv.base + "/api/actions")
            self.assertEqual(status, 200)
            self.assertIn("validate_config", actions["actions"])
            self.assertIn("cascade_cpp_smoke", actions["actions"])

            status, diagnostics = request_json(srv.base + "/api/diagnostics")
            self.assertEqual(status, 200)
            self.assertIn("paths", diagnostics)
            self.assertIn("commands", diagnostics)
            self.assertIn("security", diagnostics)

            status, initialized = request_json(
                srv.base + "/api/bootstrap",
                method="POST",
                data={"write_config": True, "force": True},
            )
            self.assertEqual(status, 200)
            self.assertTrue(initialized["ok"])
            self.assertTrue(initialized["changed"])
            self.assertIn(str(video), initialized["text"])

            status, config = request_json(srv.base + "/api/config")
            self.assertEqual(status, 200)
            self.assertIn("release_id:", config["text"])
            self.assertIn(str(video), config["text"])

            status, saved = request_json(srv.base + "/api/config", method="POST", data={"text": config["text"]})
            self.assertEqual(status, 200)
            self.assertTrue(saved["validation"]["ok"])

            status, run = request_json(srv.base + "/api/run", method="POST", data={"action": "validate_config", "params": {}})
            self.assertEqual(status, 200)
            self.assertEqual(run["status"], "succeeded")

            status, runs = request_json(srv.base + "/api/runs")
            self.assertEqual(status, 200)
            self.assertGreaterEqual(len(runs["runs"]), 1)

            status, payload = request_json(srv.base + "/api/log?path=/etc/passwd")
            self.assertEqual(status, 403)
            self.assertIn("outside allowed roots", payload["error"])

            status, run = request_json(
                srv.base + "/api/run",
                method="POST",
                data={"action": "strict1024_cpp_smoke", "params": {"runner": "/bin/echo", "video": str(video), "engine": str(stage1)}},
            )
            self.assertEqual(status, 200)
            self.assertEqual(run["status"], "failed")

            verify_env = os.environ.copy()
            verify_env["BASE_URL"] = srv.base
            proc = subprocess.run(
                ["bash", str(VERIFY_DEPLOYMENT)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=verify_env,
                check=False,
                timeout=15,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertIn("VERIFY_DEPLOYMENT_OK", proc.stdout)
        finally:
            srv.stop()

    def test_token_auth_cors_and_body_limit(self) -> None:
        token = "test-token"
        headers = {"X-Auth-Token": token}
        srv = WebUIServer(token=token, cors="http://client.local", max_body=128)
        try:
            srv.wait()
            status, _ = request_json(srv.base + "/api/status")
            self.assertEqual(status, 401)

            status, payload = request_json(srv.base + "/api/status", headers=headers)
            self.assertEqual(status, 200)
            self.assertTrue(payload["auth_required"])

            status, payload = request_json(srv.base + "/api/version", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(status, 200)
            self.assertEqual(payload["version"], "0.6.0")

            status, auth = request_json(srv.base + "/api/auth")
            self.assertEqual(status, 200)
            self.assertTrue(auth["auth_required"])
            self.assertFalse(auth["query_token_supported"])

            status, _ = request_json(srv.base + f"/api/status?token={token}")
            self.assertEqual(status, 401)

            req = urllib.request.Request(
                srv.base + "/api/openapi.json",
                method="OPTIONS",
                headers={"Origin": "http://client.local", "Access-Control-Request-Method": "GET"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 204)
                self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "http://client.local")

            big = "x" * 512
            status, payload = request_json(srv.base + "/api/config", method="POST", data={"text": big}, headers=headers)
            self.assertEqual(status, 413)
            self.assertIn("request body too large", payload["error"])

            verify_env = os.environ.copy()
            verify_env["BASE_URL"] = srv.base
            verify_env["JETSON_WEBUI_TOKEN"] = token
            verify_env["ENV_FILE"] = str(srv.tmp_path / "missing.env")
            proc = subprocess.run(
                ["bash", str(VERIFY_DEPLOYMENT)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=verify_env,
                check=False,
                timeout=15,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertIn("VERIFY_DEPLOYMENT_OK", proc.stdout)
        finally:
            srv.stop()

    def test_configure_access_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "jetson-yolo-webui.env"
            proc = subprocess.run(
                [
                    "bash",
                    str(CONFIGURE_ACCESS),
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "8766",
                    "--generate-token",
                    "--cors",
                    "http://client.local",
                    "--no-restart",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env={**os.environ, "ENV_FILE": str(env_file), "ALLOW_NON_ROOT": "1"},
                check=False,
                timeout=10,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout)
            text = env_file.read_text(encoding="utf-8")
            self.assertIn("JETSON_WEBUI_HOST=0.0.0.0", text)
            self.assertIn("JETSON_WEBUI_PORT=8766", text)
            self.assertIn("JETSON_WEBUI_CORS_ORIGIN=http://client.local", text)
            self.assertRegex(text, r"JETSON_WEBUI_TOKEN=.+")
            self.assertIn("GENERATED_JETSON_WEBUI_TOKEN=", proc.stdout)

    def test_external_bind_requires_token(self) -> None:
        srv = WebUIServer(host="0.0.0.0")
        try:
            output = srv.wait(expect_ready=False)
            deadline = time.time() + 5
            while srv.proc.poll() is None and time.time() < deadline:
                time.sleep(0.1)
            self.assertIsNotNone(srv.proc.poll())
            if srv.proc.stdout:
                output += srv.proc.stdout.read() or ""
            self.assertIn("Refusing to bind WebUI", output)
        finally:
            srv.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
