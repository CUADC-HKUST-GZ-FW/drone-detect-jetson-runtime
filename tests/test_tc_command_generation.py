import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import tc_apply


def test_yolov26n_alias_not_here():
    assert tc_apply.protocol_number("udp") == "17"


def test_generates_dry_run_commands():
    policy = json.loads((ROOT / "configs" / "degraded_policy.example.json").read_text())
    policy["rules"][0]["match"]["dst_ip"] = "192.0.2.2"
    commands = tc_apply.build_commands(policy, "htb")
    lines = tc_apply.printable_commands(commands.clear + commands.apply)

    assert any("qdisc add dev eth0 root handle 77: htb" in line for line in lines)
    assert any("class replace dev eth0 parent 77:1 classid 77:10 htb rate 2mbit" in line for line in lines)
    assert any("netem delay 80ms loss 2%" in line for line in lines)
    assert any("match ip protocol 17 0xff" in line for line in lines)
    assert any("match ip dport 5000 0xffff" in line for line in lines)


def test_rejects_bad_port():
    policy = json.loads((ROOT / "configs" / "degraded_policy.example.json").read_text())
    policy["rules"][0]["match"]["dst_port"] = 70000
    try:
        tc_apply.build_commands(policy)
    except ValueError as exc:
        assert "invalid port" in str(exc)
    else:
        raise AssertionError("expected invalid port")


def test_simple_backend_generates_tbf_netem():
    policy = json.loads((ROOT / "configs" / "degraded_policy.example.json").read_text())
    policy["rules"][0]["jitter_ms"] = 5
    commands = tc_apply.build_commands(policy, "simple")
    lines = tc_apply.printable_commands(commands.clear + commands.apply)

    assert any("qdisc add dev eth0 root handle 77: tbf rate 2mbit" in line for line in lines)
    assert any("qdisc add dev eth0 parent 77:1 handle 100: netem delay 80ms 5ms loss 2%" in line for line in lines)


def test_edge_agent_builds_policy_from_cloud_config():
    import edge_mqtt_agent

    message = {
        "request_id": "verify-001",
        "node_id": "jetson_01",
        "target": {
            "interface": "eth0",
            "dst_ip": "192.0.2.20",
            "dst_port": 5000,
            "protocol": "udp",
        },
        "tc": {
            "backend": "htb",
            "rate_mbps": 20,
            "delay_ms": 10,
            "jitter_ms": 2,
            "loss_percent": 0.1,
            "duration_s": 60,
        },
    }
    policy = edge_mqtt_agent.build_policy_from_config(message, "eth0", "jetson_01", 45)

    assert policy["policy_id"] == "verify-001"
    assert policy["target_node"] == "jetson_01"
    assert policy["interface"] == "eth0"
    assert policy["backend"] == "htb"
    assert policy["safety"]["auto_rollback_seconds"] == 60
    assert policy["rules"][0]["match"]["dst_ip"] == "192.0.2.20"
    assert policy["rules"][0]["bandwidth_mbit"] == 20
    assert policy["rules"][0]["jitter_ms"] == 2
