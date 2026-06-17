#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import struct
import subprocess
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_DIR", "/workspace"))
DEFAULT_INTERFACE = os.environ.get("DRONE_INTERFACE", "eth0")
STATE_ROOT = PROJECT_ROOT / "results" / "mqtt_agent"
NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        encoded = value % 128
        value //= 128
        if value:
            encoded |= 128
        out.append(encoded)
        if not value:
            return bytes(out)


def encode_string(value: str) -> bytes:
    data = value.encode("utf-8")
    return struct.pack("!H", len(data)) + data


def decode_varint(sock: socket.socket) -> int:
    multiplier = 1
    value = 0
    while True:
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("connection closed while reading MQTT remaining length")
        byte = chunk[0]
        value += (byte & 127) * multiplier
        if not byte & 128:
            return value
        multiplier *= 128
        if multiplier > 128**4:
            raise ValueError("malformed MQTT remaining length")


class MiniMqttClient:
    def __init__(self, host: str, port: int, client_id: str, keepalive: int = 30) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.keepalive = keepalive
        self.sock: socket.socket | None = None
        self.packet_id = 1
        self.last_io = time.monotonic()

    def connect(self) -> None:
        self.close()
        sock = socket.create_connection((self.host, self.port), timeout=10)
        sock.settimeout(1.0)
        variable = encode_string("MQTT") + bytes([4, 2]) + struct.pack("!H", self.keepalive)
        payload = encode_string(self.client_id)
        sock.sendall(bytes([0x10]) + encode_varint(len(variable) + len(payload)) + variable + payload)
        packet_type, body = self.read_packet(sock)
        if packet_type != 0x20 or len(body) < 2 or body[1] != 0:
            raise ConnectionError(f"MQTT CONNACK failed: type=0x{packet_type:02x} body={body!r}")
        self.sock = sock
        self.last_io = time.monotonic()

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def read_packet(self, sock: socket.socket | None = None) -> tuple[int, bytes]:
        sock = sock or self.sock
        if sock is None:
            raise ConnectionError("MQTT socket is not connected")
        first = sock.recv(1)
        if not first:
            raise ConnectionError("connection closed")
        remaining = decode_varint(sock)
        body = b""
        while len(body) < remaining:
            chunk = sock.recv(remaining - len(body))
            if not chunk:
                raise ConnectionError("connection closed while reading MQTT body")
            body += chunk
        self.last_io = time.monotonic()
        return first[0], body

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        if self.sock is None:
            raise ConnectionError("MQTT socket is not connected")
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        body = encode_string(topic) + data
        self.sock.sendall(bytes([0x30]) + encode_varint(len(body)) + body)
        self.last_io = time.monotonic()

    def subscribe(self, topic: str) -> None:
        if self.sock is None:
            raise ConnectionError("MQTT socket is not connected")
        packet_id = self.packet_id
        self.packet_id = 1 if self.packet_id >= 65535 else self.packet_id + 1
        body = struct.pack("!H", packet_id) + encode_string(topic) + b"\x00"
        self.sock.sendall(bytes([0x82]) + encode_varint(len(body)) + body)
        self.last_io = time.monotonic()

    def ping_if_needed(self) -> None:
        if self.sock is None:
            raise ConnectionError("MQTT socket is not connected")
        if time.monotonic() - self.last_io > max(5, self.keepalive // 2):
            self.sock.sendall(b"\xc0\x00")
            self.last_io = time.monotonic()


def parse_publish(packet_type: int, body: bytes) -> tuple[str, bytes] | None:
    if packet_type >> 4 != 3 or len(body) < 2:
        return None
    topic_len = struct.unpack("!H", body[:2])[0]
    topic_start = 2
    topic_end = topic_start + topic_len
    if topic_end > len(body):
        return None
    topic = body[topic_start:topic_end].decode("utf-8", errors="replace")
    qos = (packet_type >> 1) & 0x03
    payload_start = topic_end + (2 if qos else 0)
    return topic, body[payload_start:]


def read_cpu() -> tuple[int, int]:
    with Path("/proc/stat").open("r", encoding="utf-8") as fh:
        parts = [int(x) for x in fh.readline().split()[1:]]
    idle = parts[3] + parts[4]
    return sum(parts), idle


def cpu_percent(prev: tuple[int, int], cur: tuple[int, int]) -> float:
    total_delta = cur[0] - prev[0]
    idle_delta = cur[1] - prev[1]
    if total_delta <= 0:
        return 0.0
    return round(100.0 * (1.0 - idle_delta / total_delta), 2)


def memory_percent() -> float | None:
    data: dict[str, int] = {}
    with Path("/proc/meminfo").open("r", encoding="utf-8") as fh:
        for line in fh:
            key, value = line.split(":", 1)
            data[key] = int(value.strip().split()[0])
    total = data.get("MemTotal")
    available = data.get("MemAvailable")
    if not total or available is None:
        return None
    return round(100.0 * (1.0 - available / total), 2)


def read_netdev(interface: str) -> dict[str, int]:
    with Path("/proc/net/dev").open("r", encoding="utf-8") as fh:
        for line in fh:
            if ":" not in line:
                continue
            name, rest = line.split(":", 1)
            if name.strip() != interface:
                continue
            vals = [int(x) for x in rest.split()]
            return {
                "rx_bytes": vals[0],
                "rx_packets": vals[1],
                "rx_drop": vals[3],
                "tx_bytes": vals[8],
                "tx_packets": vals[9],
                "tx_drop": vals[11],
            }
    return {}


def run_text(cmd: list[str], timeout: float = 3.0) -> str:
    try:
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        return proc.stdout.strip()
    except Exception as exc:
        return f"error: {type(exc).__name__}: {exc}"


def run_host_text(command: str, timeout: float = 3.0) -> str:
    nsenter = [
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
        command,
    ]
    if Path("/usr/bin/nsenter").exists() or Path("/bin/nsenter").exists():
        return run_text(nsenter, timeout=timeout)
    return run_text(["bash", "-lc", command], timeout=timeout)


def parse_tegrastats(text: str) -> dict[str, Any]:
    line = text.strip().splitlines()[-1] if text.strip() else ""
    gpu = None
    temp = None
    m = re.search(r"GR3D_FREQ\s+(\d+)%", line)
    if m:
        gpu = int(m.group(1))
    m = re.search(r"GPU@([0-9.]+)C", line)
    if m:
        temp = float(m.group(1))
    return {"raw": line or None, "gpu_percent": gpu, "temperature_c": temp}


def sample_tegrastats() -> dict[str, Any]:
    text = run_host_text("command -v tegrastats >/dev/null && timeout 1 tegrastats --interval 500 || true", timeout=2.5)
    return parse_tegrastats(text)


def parse_tc(text: str, include_raw: bool = False) -> dict[str, Any]:
    backlog_packets = 0
    dropped_packets = 0
    overlimits = 0
    for line in text.splitlines():
        m = re.search(r"dropped\s+(\d+),\s+overlimits\s+(\d+)", line)
        if m:
            dropped_packets += int(m.group(1))
            overlimits += int(m.group(2))
        m = re.search(r"backlog\s+\S+\s+(\d+)p", line)
        if m:
            backlog_packets += int(m.group(1))
    stats = {
        "backlog_packets": backlog_packets,
        "dropped_packets": dropped_packets,
        "overlimits": overlimits,
    }
    if include_raw:
        stats["raw"] = text[-4000:]
    return stats


def ping_rtt_ms(target: str | None) -> float | None:
    if not target:
        return None
    text = run_text(["ping", "-c", "1", "-W", "1", target], timeout=2.0)
    m = re.search(r"time=([0-9.]+)\s*ms", text)
    return float(m.group(1)) if m else None


def latest_yolo_summary() -> dict[str, Any]:
    root = PROJECT_ROOT / "results" / "yolo"
    if not root.exists():
        return {}
    summaries = sorted(root.rglob("summary.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not summaries:
        return {}
    try:
        data = json.loads(summaries[0].read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {
        "model": data.get("model_requested") or data.get("model_resolved"),
        "backend": "pytorch_cuda" if data.get("status") == "ok" else None,
        "infer_latency_ms": data.get("avg_infer_ms"),
        "detections": None,
        "summary_path": str(summaries[0].relative_to(PROJECT_ROOT)),
    }


def build_telemetry(args: argparse.Namespace, prev_cpu: tuple[int, int], prev_net: dict[str, int], interval_s: float) -> tuple[dict[str, Any], tuple[int, int], dict[str, int]]:
    cur_cpu = read_cpu()
    cur_net = read_netdev(args.interface)
    tc_text = run_text(["tc", "-s", "qdisc", "show", "dev", args.interface], timeout=2.0)
    tegra = sample_tegrastats()
    elapsed = max(interval_s, 0.001)
    rx_mbps = None
    tx_mbps = None
    if cur_net and prev_net:
        rx_mbps = round((cur_net.get("rx_bytes", 0) - prev_net.get("rx_bytes", 0)) * 8 / elapsed / 1_000_000, 3)
        tx_mbps = round((cur_net.get("tx_bytes", 0) - prev_net.get("tx_bytes", 0)) * 8 / elapsed / 1_000_000, 3)
    ai = latest_yolo_summary()
    payload = {
        "node_id": args.node_id,
        "timestamp": utc_now(),
        "interface": args.interface,
        "role": args.node_role,
        "system": {
            "cpu_percent": cpu_percent(prev_cpu, cur_cpu),
            "memory_percent": memory_percent(),
            "gpu_percent": tegra.get("gpu_percent"),
            "gpu_memory_percent": None,
            "temperature_c": tegra.get("temperature_c"),
        },
        "network": {
            "rx_mbps": rx_mbps,
            "tx_mbps": tx_mbps,
            "rtt_ms": ping_rtt_ms(args.rtt_target),
            **parse_tc(tc_text, include_raw=args.include_raw_qdisc),
        },
        "video": {
            "stream_id": args.stream_id,
            "fps": None,
            "bitrate_mbps": None,
            "resolution": None,
            "encode_latency_ms": None,
        },
        "ai": ai or {
            "model": "yolov26n",
            "backend": None,
            "infer_latency_ms": None,
            "detections": None,
        },
    }
    return payload, cur_cpu, cur_net


def valid_name(value: str, label: str) -> str:
    if not NAME_RE.match(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def first_number(*values: Any, default: float | None = None) -> float | None:
    for value in values:
        if value is None:
            continue
        return float(value)
    return default


def tc_backend(value: Any) -> str:
    backend = str(value or os.environ.get("EDGE_TC_BACKEND", "simple")).lower()
    if backend in {"simple", "htb"}:
        return backend
    raise ValueError(f"unsupported tc backend: {backend!r}")


def build_policy_from_config(message: dict[str, Any], default_interface: str, default_node_id: str, default_rollback: int) -> dict[str, Any]:
    target = message.get("target") or {}
    tc = message.get("tc") or {}
    node_id = str(message.get("node_id") or default_node_id)
    interface = valid_name(str(target.get("interface") or message.get("interface") or default_interface), "interface")
    rate = first_number(tc.get("rate_mbps"), message.get("bandwidth_mbps"), default=20.0)
    delay = first_number(tc.get("delay_ms"), message.get("latency_ms"), default=0.0)
    jitter = first_number(tc.get("jitter_ms"), message.get("jitter_ms"), default=0.0)
    loss = first_number(tc.get("loss_percent"), message.get("loss_percent"), default=0.0)
    duration = int(first_number(tc.get("duration_s"), message.get("duration_s"), default=default_rollback) or default_rollback)
    dst_ip = (target.get("dst_ip") or message.get("dst_ip") or "JETSON_B_IP")
    dst_port = int(target.get("dst_port") or message.get("dst_port") or 5000)
    protocol = str(target.get("protocol") or message.get("protocol") or "udp").lower()
    request_id = str(message.get("request_id") or f"mqtt-{int(time.time())}")
    policy = {
        "policy_id": request_id,
        "target_node": node_id,
        "interface": interface,
        "mode": "dry-run",
        "backend": tc_backend(tc.get("backend") or message.get("backend")),
        "root_rate_mbit": max(float(rate or 20.0), 1.0),
        "safety": {
            "dry_run": True,
            "auto_rollback_seconds": max(duration, 1),
            "require_confirm": True,
            "allow_ssh_interface": True,
        },
        "default": {
            "bandwidth_mbit": max(float(rate or 20.0), 1.0),
            "priority": 7,
        },
        "rules": [
            {
                "name": str(target.get("service") or "mqtt-configured-flow"),
                "match": {
                    "dst_ip": dst_ip,
                    "dst_port": dst_port,
                    "protocol": protocol,
                },
                "bandwidth_mbit": max(float(rate or 20.0), 0.1),
                "delay_ms": max(float(delay or 0.0), 0.0),
                "jitter_ms": max(float(jitter or 0.0), 0.0),
                "loss_percent": min(max(float(loss or 0.0), 0.0), 100.0),
                "priority": 1,
            }
        ],
    }
    return policy


def run_tc_apply(policy: dict[str, Any], action: str, dry_run_only: bool, auto_rollback: int) -> dict[str, Any]:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    policy_dir = STATE_ROOT / "policies"
    policy_dir.mkdir(parents=True, exist_ok=True)
    request_id = str(policy.get("policy_id") or int(time.time()))
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", request_id)
    policy_path = policy_dir / f"{safe_id}.json"
    policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")

    if action == "clear":
        cmd = ["python3", "scripts/tc_apply.py", "--interface", policy["interface"], "--clear", "--yes"]
    else:
        cmd = ["python3", "scripts/tc_apply.py", "--config", str(policy_path)]
        if dry_run_only or action == "dry-run":
            cmd.append("--dry-run")
        else:
            cmd.extend(["--apply", "--yes", "--allow-ssh-interface", "--auto-rollback-seconds", str(auto_rollback)])

    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=120)
    token = None
    for line in proc.stdout.splitlines():
        if line.startswith("rollback_guard_token="):
            token = line.split("=", 1)[1].strip()
    return {
        "command": " ".join(cmd),
        "policy_path": str(policy_path),
        "returncode": proc.returncode,
        "stdout": proc.stdout[-12000:],
        "stderr": "",
        "rollback_guard_token": token,
    }


def handle_config(args: argparse.Namespace, message: dict[str, Any]) -> dict[str, Any]:
    msg_node = message.get("node_id")
    if msg_node not in (None, "", args.node_id, "*"):
        return {
            "request_id": message.get("request_id"),
            "node_id": args.node_id,
            "timestamp": utc_now(),
            "status": "ignored",
            "reason": f"message node_id {msg_node!r} does not match {args.node_id!r}",
        }
    tc = message.get("tc") or {}
    action = str(tc.get("action") or message.get("action") or "replace").lower()
    if action == "replace":
        action = "apply"
    policy = build_policy_from_config(message, args.interface, args.node_id, args.default_rollback_seconds)
    auto_rollback = int(policy["safety"]["auto_rollback_seconds"])
    dry_run_only = args.dry_run_only or bool(tc.get("dry_run"))
    result = run_tc_apply(policy, action, dry_run_only, auto_rollback)
    status = "applied"
    if dry_run_only or action == "dry-run":
        status = "dry_run"
    if result["returncode"] != 0:
        status = "failed"
    return {
        "request_id": message.get("request_id") or policy["policy_id"],
        "node_id": args.node_id,
        "timestamp": utc_now(),
        "status": status,
        "interface": policy["interface"],
        "applied_command": result["command"],
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "policy_path": result["policy_path"],
        "rollback_guard_token": result.get("rollback_guard_token"),
        "rollback_guard_seconds": None if dry_run_only else auto_rollback,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jetson MQTT telemetry/config/ack edge agent")
    parser.add_argument("--mqtt-host", default=os.environ.get("MQTT_HOST", "127.0.0.1"))
    parser.add_argument("--mqtt-port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    parser.add_argument("--node-id", default=os.environ.get("EDGE_NODE_ID", os.environ.get("NODE_ROLE", "jetson_01")))
    parser.add_argument("--node-role", default=os.environ.get("NODE_ROLE", "standalone"))
    parser.add_argument("--interface", default=DEFAULT_INTERFACE)
    parser.add_argument("--telemetry-interval", type=float, default=float(os.environ.get("EDGE_TELEMETRY_INTERVAL", "1.0")))
    parser.add_argument("--stream-id", default=os.environ.get("EDGE_STREAM_ID", "uav_fire_video"))
    parser.add_argument("--rtt-target", default=os.environ.get("EDGE_RTT_TARGET"))
    parser.add_argument("--default-rollback-seconds", type=int, default=int(os.environ.get("EDGE_DEFAULT_ROLLBACK_SECONDS", "60")))
    parser.add_argument("--dry-run-only", action="store_true", default=os.environ.get("EDGE_TC_DRY_RUN_ONLY", "0") == "1")
    parser.add_argument("--include-raw-qdisc", action="store_true", default=os.environ.get("EDGE_TELEMETRY_INCLUDE_RAW_QDISC", "0") == "1")
    parser.add_argument("--once", action="store_true", help="publish one telemetry sample and exit")
    return parser


def run_agent(args: argparse.Namespace) -> None:
    telemetry_topic = os.environ.get("EDGE_TELEMETRY_TOPIC", f"6g/edge/{args.node_id}/telemetry")
    config_topic = os.environ.get("EDGE_CONFIG_TOPIC", f"6g/edge/{args.node_id}/config")
    ack_topic = os.environ.get("EDGE_ACK_TOPIC", f"6g/edge/{args.node_id}/ack")
    client = MiniMqttClient(args.mqtt_host, args.mqtt_port, f"{args.node_id}-{socket.gethostname()}-{os.getpid()}")
    prev_cpu = read_cpu()
    prev_net = read_netdev(args.interface)
    next_telemetry = 0.0
    last_sample = time.monotonic()

    while True:
        try:
            client.connect()
            client.subscribe(config_topic)
            while True:
                now = time.monotonic()
                if now >= next_telemetry:
                    elapsed = max(now - last_sample, args.telemetry_interval)
                    payload, prev_cpu, prev_net = build_telemetry(args, prev_cpu, prev_net, elapsed)
                    client.publish(telemetry_topic, payload)
                    last_sample = now
                    next_telemetry = now + args.telemetry_interval
                    if args.once:
                        return
                try:
                    packet_type, body = client.read_packet()
                except socket.timeout:
                    client.ping_if_needed()
                    continue
                parsed = parse_publish(packet_type, body)
                if not parsed:
                    continue
                _, raw_payload = parsed
                try:
                    message = json.loads(raw_payload.decode("utf-8"))
                    ack = handle_config(args, message)
                except Exception as exc:  # noqa: BLE001
                    ack = {
                        "request_id": None,
                        "node_id": args.node_id,
                        "timestamp": utc_now(),
                        "status": "failed",
                        "interface": args.interface,
                        "returncode": 1,
                        "stdout": "",
                        "stderr": f"{type(exc).__name__}: {exc}",
                    }
                client.publish(ack_topic, ack)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"{utc_now()} edge_mqtt_agent reconnecting after {type(exc).__name__}: {exc}", flush=True)
            client.close()
            if args.once:
                raise
            time.sleep(3)


def main() -> int:
    args = build_parser().parse_args()
    if args.rtt_target is None:
        args.rtt_target = args.mqtt_host
    run_agent(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
