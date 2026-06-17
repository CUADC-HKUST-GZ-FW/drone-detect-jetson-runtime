#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import secrets
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT_HANDLE = "77:"
DEFAULT_CLASS_MINOR = 999
STATE_DIR = Path("results/tc_state")


@dataclass
class TcCommandSet:
    clear: list[list[str]]
    apply: list[list[str]]


def load_policy(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def replace_dst_ip(policy: dict[str, Any], dst_ip: str | None) -> None:
    if not dst_ip:
        return
    validate_ip(dst_ip)
    for rule in policy.get("rules", []):
        match = rule.get("match") or {}
        if match.get("dst_ip") == "JETSON_B_IP":
            match["dst_ip"] = dst_ip
            rule["match"] = match


def shell_join(cmd: list[str]) -> str:
    return " ".join(shlex.quote(str(x)) for x in cmd)


def protocol_number(protocol: str) -> str:
    protocol = protocol.lower()
    if protocol == "udp":
        return "17"
    if protocol == "tcp":
        return "6"
    raise ValueError(f"unsupported protocol: {protocol}")


def validate_interface(interface: str) -> None:
    if not interface or "/" in interface or interface.startswith("-"):
        raise ValueError(f"invalid interface: {interface!r}")


def validate_ip(value: str) -> str:
    ipaddress.ip_address(value)
    return value


def validate_port(value: Any) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError(f"invalid port: {value!r}")
    return port


def class_id(idx: int) -> str:
    return f"77:{idx}"


def build_simple_commands(policy: dict[str, Any]) -> TcCommandSet:
    interface = str(policy["interface"])
    validate_interface(interface)
    rules = policy.get("rules", [])
    for rule in rules:
        match = rule.get("match") or {}
        if match.get("src_ip") and str(match["src_ip"]) != "JETSON_B_IP":
            validate_ip(str(match["src_ip"]))
        if match.get("dst_ip") and str(match["dst_ip"]) != "JETSON_B_IP":
            validate_ip(str(match["dst_ip"]))
        if match.get("src_port"):
            validate_port(match["src_port"])
        if match.get("dst_port"):
            validate_port(match["dst_port"])
        if match.get("protocol"):
            protocol_number(str(match["protocol"]))
    first = rules[0] if rules else {}
    default = policy.get("default") or {}
    rate = float(first.get("bandwidth_mbit") or default.get("bandwidth_mbit") or policy.get("root_rate_mbit", 100))
    delay_ms = float(first.get("delay_ms", 0) or 0)
    jitter_ms = float(first.get("jitter_ms", 0) or 0)
    loss_percent = float(first.get("loss_percent", 0) or 0)
    burst_kbit = int(max(rate * 128, 64))
    latency_ms = int(max(delay_ms + 50, 50))
    clear = [["tc", "qdisc", "del", "dev", interface, "root"]]
    apply: list[list[str]] = [
        ["tc", "qdisc", "add", "dev", interface, "root", "handle", "77:", "tbf", "rate", f"{rate:g}mbit", "burst", f"{burst_kbit}kbit", "latency", f"{latency_ms}ms"],
    ]
    if delay_ms > 0 or loss_percent > 0:
        netem = ["tc", "qdisc", "add", "dev", interface, "parent", "77:1", "handle", "100:", "netem"]
        if delay_ms > 0:
            netem.extend(["delay", f"{delay_ms:g}ms"])
            if jitter_ms > 0:
                netem.append(f"{jitter_ms:g}ms")
        if loss_percent > 0:
            netem.extend(["loss", f"{loss_percent:g}%"])
        apply.append(netem)
    apply.append(["#", "backend=simple applies impairment to all egress traffic on the interface"])
    return TcCommandSet(clear=clear, apply=apply)


def build_htb_commands(policy: dict[str, Any]) -> TcCommandSet:
    interface = str(policy["interface"])
    validate_interface(interface)
    root_rate = float(policy.get("root_rate_mbit", 100))
    default_rate = float((policy.get("default") or {}).get("bandwidth_mbit", max(root_rate / 2, 1)))

    clear = [["tc", "qdisc", "del", "dev", interface, "root"]]
    apply: list[list[str]] = [
        ["tc", "qdisc", "add", "dev", interface, "root", "handle", ROOT_HANDLE, "htb", "default", str(DEFAULT_CLASS_MINOR)],
        ["tc", "class", "replace", "dev", interface, "parent", "77:0", "classid", "77:1", "htb", "rate", f"{root_rate:g}mbit", "ceil", f"{root_rate:g}mbit"],
        ["tc", "class", "replace", "dev", interface, "parent", "77:1", "classid", f"77:{DEFAULT_CLASS_MINOR}", "htb", "rate", f"{default_rate:g}mbit", "ceil", f"{root_rate:g}mbit", "prio", str((policy.get("default") or {}).get("priority", 7))],
    ]

    for idx, rule in enumerate(policy.get("rules", []), start=10):
        rule_name = str(rule.get("name", f"rule-{idx}"))
        match = rule.get("match") or {}
        rate = float(rule.get("bandwidth_mbit", default_rate))
        ceil = float(rule.get("ceil_mbit", root_rate))
        priority = int(rule.get("priority", idx))
        delay_ms = float(rule.get("delay_ms", 0) or 0)
        jitter_ms = float(rule.get("jitter_ms", 0) or 0)
        loss_percent = float(rule.get("loss_percent", 0) or 0)
        cid = class_id(idx)

        apply.append(["tc", "class", "replace", "dev", interface, "parent", "77:1", "classid", cid, "htb", "rate", f"{rate:g}mbit", "ceil", f"{ceil:g}mbit", "prio", str(priority)])

        if delay_ms > 0 or loss_percent > 0:
            netem = ["tc", "qdisc", "replace", "dev", interface, "parent", cid, "handle", f"{idx}0:", "netem"]
            if delay_ms > 0:
                netem.extend(["delay", f"{delay_ms:g}ms"])
                if jitter_ms > 0:
                    netem.append(f"{jitter_ms:g}ms")
            if loss_percent > 0:
                netem.extend(["loss", f"{loss_percent:g}%"])
            apply.append(netem)

        filter_cmd = ["tc", "filter", "replace", "dev", interface, "protocol", "ip", "parent", ROOT_HANDLE, "prio", str(priority), "u32"]
        protocol = match.get("protocol")
        if protocol:
            filter_cmd.extend(["match", "ip", "protocol", protocol_number(str(protocol)), "0xff"])
        if match.get("src_ip"):
            filter_cmd.extend(["match", "ip", "src", validate_ip(str(match["src_ip"]))])
        if match.get("dst_ip"):
            dst_ip = str(match["dst_ip"])
            if dst_ip != "JETSON_B_IP":
                validate_ip(dst_ip)
            filter_cmd.extend(["match", "ip", "dst", dst_ip])
        if match.get("src_port"):
            filter_cmd.extend(["match", "ip", "sport", str(validate_port(match["src_port"])), "0xffff"])
        if match.get("dst_port"):
            filter_cmd.extend(["match", "ip", "dport", str(validate_port(match["dst_port"])), "0xffff"])
        filter_cmd.extend(["flowid", cid])
        apply.append(filter_cmd)

        apply.append(["#", f"rule={rule_name}"])

    return TcCommandSet(clear=clear, apply=apply)


def build_commands(policy: dict[str, Any], backend_override: str | None = None) -> TcCommandSet:
    backend = (backend_override or policy.get("backend") or "htb").lower()
    if backend in {"simple", "netem", "tbf"}:
        return build_simple_commands(policy)
    if backend == "htb":
        return build_htb_commands(policy)
    raise ValueError(f"unsupported backend: {backend}")


def printable_commands(commands: list[list[str]]) -> list[str]:
    rows = []
    for cmd in commands:
        if cmd and cmd[0] == "#":
            rows.append("# " + " ".join(cmd[1:]))
        else:
            rows.append(shell_join(cmd))
    return rows


def run_command(cmd: list[str], log_fh: Any | None = None, ignore_missing_qdisc: bool = False) -> int:
    if cmd and cmd[0] == "#":
        if log_fh:
            log_fh.write("# " + " ".join(cmd[1:]) + "\n")
        return 0
    if log_fh:
        log_fh.write("$ " + shell_join(cmd) + "\n")
        log_fh.flush()
    proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if log_fh and proc.stdout:
        log_fh.write(proc.stdout)
        log_fh.flush()
    if ignore_missing_qdisc and proc.returncode != 0:
        ignored = (
            "No such file",
            "Cannot delete qdisc with handle of zero",
            "Invalid argument",
        )
        if any(text in proc.stdout for text in ignored):
            return 0
    return proc.returncode


def capture_tc(interface: str, out_dir: Path, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    commands = {
        f"{label}_qdisc.txt": ["tc", "-s", "qdisc", "show", "dev", interface],
        f"{label}_class.txt": ["tc", "-s", "class", "show", "dev", interface],
        f"{label}_filter.txt": ["tc", "-s", "filter", "show", "dev", interface],
    }
    for name, cmd in commands.items():
        proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        (out_dir / name).write_text(proc.stdout, encoding="utf-8")


def route_interface_for_ssh() -> str | None:
    ssh_client = os.environ.get("SSH_CLIENT", "").split()
    if not ssh_client:
        return None
    remote_ip = ssh_client[0]
    proc = subprocess.run(["ip", "route", "get", remote_ip], check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    parts = proc.stdout.split()
    if "dev" in parts:
        return parts[parts.index("dev") + 1]
    return None


def ensure_apply_safe(policy: dict[str, Any], args: argparse.Namespace) -> int:
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise RuntimeError("apply requires root; run: sudo python3 scripts/tc_apply.py ...")

    safety = policy.get("safety") or {}
    rollback_seconds = int(args.auto_rollback_seconds or safety.get("auto_rollback_seconds") or 0)
    if rollback_seconds <= 0:
        raise RuntimeError("apply requires safety.auto_rollback_seconds or --auto-rollback-seconds > 0")

    interface = str(policy["interface"])
    ssh_interface = route_interface_for_ssh()
    allow_ssh = bool(args.allow_ssh_interface or safety.get("allow_ssh_interface"))
    if ssh_interface and interface == ssh_interface and not allow_ssh:
        raise RuntimeError(f"refusing to modify current SSH interface {interface}; pass --allow-ssh-interface to override")
    return rollback_seconds


def create_guard(interface: str, token: str, seconds: int, state_dir: Path) -> Path:
    guard_script = state_dir / f"rollback_guard_{token}.sh"
    confirm_file = state_dir / f"confirm_{token}.token"
    log_file = state_dir / f"rollback_guard_{token}.log"
    guard_script.write_text(
        f"""#!/usr/bin/env bash
set -u
sleep {seconds}
if [ ! -f {shlex.quote(str(confirm_file))} ]; then
  echo "$(date -Is) rollback clearing {interface}" >> {shlex.quote(str(log_file))}
  tc qdisc del dev {shlex.quote(interface)} root >> {shlex.quote(str(log_file))} 2>&1 || true
else
  echo "$(date -Is) confirmed; no rollback" >> {shlex.quote(str(log_file))}
fi
""",
        encoding="utf-8",
    )
    guard_script.chmod(0o700)
    subprocess.Popen(["nohup", "bash", str(guard_script)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return confirm_file


def do_status(interface: str) -> int:
    for cmd in (
        ["tc", "-s", "qdisc", "show", "dev", interface],
        ["tc", "-s", "class", "show", "dev", interface],
        ["tc", "-s", "filter", "show", "dev", interface],
    ):
        print("$ " + shell_join(cmd))
        subprocess.run(cmd, check=False)
    return 0


def do_confirm(token: str) -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f"confirm_{token}.token"
    path.write_text(time.strftime("%Y-%m-%dT%H:%M:%S%z") + "\n", encoding="utf-8")
    print(f"confirmed rollback guard token: {token}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--rollback", type=Path)
    parser.add_argument("--confirm")
    parser.add_argument("--interface")
    parser.add_argument("--allow-ssh-interface", action="store_true")
    parser.add_argument("--auto-rollback-seconds", type=int, default=0)
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument("--set-dst-ip")
    parser.add_argument("--backend", choices=["htb", "simple"])
    args = parser.parse_args()

    if args.confirm:
        return do_confirm(args.confirm)

    if args.status:
        if not args.interface:
            parser.error("--interface is required with --status")
        validate_interface(args.interface)
        return do_status(args.interface)

    if args.clear:
        if not args.interface:
            parser.error("--interface is required with --clear")
        if not args.yes:
            parser.error("--clear requires --yes")
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            raise RuntimeError("clear requires root; run: sudo python3 scripts/tc_apply.py --interface ... --clear --yes")
        validate_interface(args.interface)
        args.state_dir.mkdir(parents=True, exist_ok=True)
        capture_tc(args.interface, args.state_dir, "before_clear")
        with (args.state_dir / "clear.log").open("a", encoding="utf-8") as log_fh:
            code = run_command(["tc", "qdisc", "del", "dev", args.interface, "root"], log_fh, ignore_missing_qdisc=True)
        capture_tc(args.interface, args.state_dir, "after_clear")
        return code

    if not args.config:
        parser.error("--config is required for dry-run/apply")

    policy = load_policy(args.config)
    replace_dst_ip(policy, args.set_dst_ip)
    commands = build_commands(policy, args.backend)
    dry_run = args.dry_run or not args.apply

    print(f"policy_id={policy.get('policy_id', 'unknown')}")
    print(f"interface={policy['interface']}")
    print(f"mode={'dry-run' if dry_run else 'apply'}")
    print("commands:")
    for line in printable_commands(commands.clear + commands.apply):
        print(line)

    if dry_run:
        return 0

    if not args.yes:
        parser.error("--apply requires --yes")

    try:
        rollback_seconds = ensure_apply_safe(policy, args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    interface = str(policy["interface"])
    token = secrets.token_urlsafe(12)
    state_dir = args.state_dir / time.strftime("%Y%m%d_%H%M%S")
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "policy.json").write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")
    capture_tc(interface, state_dir, "before_apply")

    with (state_dir / "apply.log").open("w", encoding="utf-8") as log_fh:
        for cmd in commands.clear:
            code = run_command(cmd, log_fh, ignore_missing_qdisc=True)
            if code != 0:
                return code
        for cmd in commands.apply:
            code = run_command(cmd, log_fh)
            if code != 0:
                return code

    capture_tc(interface, state_dir, "after_apply")
    create_guard(interface, token, rollback_seconds, args.state_dir)
    print(f"rollback_guard_token={token}")
    print(f"rollback_guard_seconds={rollback_seconds}")
    print(f"confirm command: python3 scripts/tc_apply.py --confirm {token}")
    print(f"state_dir={state_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
