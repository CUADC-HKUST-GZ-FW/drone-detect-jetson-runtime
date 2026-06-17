#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path


def read_mem() -> dict[str, int]:
    data: dict[str, int] = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as fh:
        for line in fh:
            key, value = line.split(":", 1)
            data[key] = int(value.strip().split()[0])
    return data


def read_cpu() -> tuple[int, int]:
    with open("/proc/stat", "r", encoding="utf-8") as fh:
        parts = fh.readline().split()[1:]
    nums = [int(x) for x in parts]
    idle = nums[3] + nums[4]
    total = sum(nums)
    return total, idle


def cpu_percent(prev: tuple[int, int], cur: tuple[int, int]) -> float:
    total_delta = cur[0] - prev[0]
    idle_delta = cur[1] - prev[1]
    if total_delta <= 0:
        return 0.0
    return round(100.0 * (1.0 - idle_delta / total_delta), 2)


def read_netdev(interface: str) -> dict[str, int]:
    with open("/proc/net/dev", "r", encoding="utf-8") as fh:
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
                "rx_errs": vals[2],
                "rx_drop": vals[3],
                "tx_bytes": vals[8],
                "tx_packets": vals[9],
                "tx_errs": vals[10],
                "tx_drop": vals[11],
            }
    return {}


def run_text(cmd: list[str], timeout: float = 2.0) -> str:
    try:
        proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return proc.stdout.strip()
    except Exception as exc:
        return f"error: {type(exc).__name__}: {exc}"


def sample_tegrastats() -> dict[str, object]:
    path = shutil_which("tegrastats")
    if not path:
        return {"available": False}
    try:
        proc = subprocess.run(["timeout", "1", path, "--interval", "500"], check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=2)
        line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    except Exception as exc:
        return {"available": True, "error": f"{type(exc).__name__}: {exc}"}
    return {"available": True, "raw": line, "gpu_percent": parse_gpu_percent(line)}


def shutil_which(name: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def parse_gpu_percent(line: str) -> int | None:
    match = re.search(r"GR3D_FREQ\s+(\d+)%", line)
    if not match:
        return None
    return int(match.group(1))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interface", default="eth0")
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--output", required=True)
    parser.add_argument("--include-tc", action="store_true")
    args = parser.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    prev_cpu = read_cpu()
    end_time = time.time() + args.duration
    with out_path.open("w", encoding="utf-8") as fh:
        while time.time() < end_time:
            cur_cpu = read_cpu()
            mem = read_mem()
            row = {
                "ts": time.time(),
                "iso_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "interface": args.interface,
                "cpu_percent": cpu_percent(prev_cpu, cur_cpu),
                "mem_total_kib": mem.get("MemTotal"),
                "mem_available_kib": mem.get("MemAvailable"),
                "net": read_netdev(args.interface),
                "tegrastats": sample_tegrastats(),
            }
            if args.include_tc:
                row["tc_qdisc"] = run_text(["tc", "-s", "qdisc", "show", "dev", args.interface])
                row["tc_class"] = run_text(["tc", "-s", "class", "show", "dev", args.interface])
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            prev_cpu = cur_cpu
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

