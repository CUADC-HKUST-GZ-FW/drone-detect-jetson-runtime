# Network Policy Schema

The `tc` tool accepts a JSON file with this shape:

```json
{
  "policy_id": "demo-degraded",
  "target_node": "jetson-a",
  "interface": "eth0",
  "mode": "dry-run",
  "root_rate_mbit": 50,
  "safety": {
    "dry_run": true,
    "auto_rollback_seconds": 60,
    "require_confirm": true,
    "allow_ssh_interface": false
  },
  "default": {
    "bandwidth_mbit": 20,
    "priority": 7
  },
  "rules": [
    {
      "name": "video-flow",
      "match": {
        "dst_ip": "JETSON_B_IP",
        "dst_port": 5000,
        "protocol": "udp"
      },
      "bandwidth_mbit": 8,
      "delay_ms": 30,
      "loss_percent": 0.5,
      "priority": 1
    }
  ]
}
```

## Fields

| Field | Required | Description |
| --- | --- | --- |
| `policy_id` | yes | Human-readable policy id used in logs. |
| `target_node` | no | Label only. |
| `interface` | yes | Linux interface to configure. |
| `mode` | no | `dry-run` or `apply`; CLI flags still control execution. |
| `backend` | no | `simple` for TBF + netem, or `htb` for per-flow classes when HTB is available. |
| `root_rate_mbit` | no | Parent HTB capacity. Default: 100. |
| `safety.dry_run` | no | Keeps config non-mutating by default. |
| `safety.auto_rollback_seconds` | yes for apply | Rollback guard delay. Must be positive for apply. |
| `safety.allow_ssh_interface` | no | Allows modifying current SSH interface. Default false. |
| `default.bandwidth_mbit` | no | Default class rate for unmatched traffic. |
| `rules[].match.dst_ip` | no | Destination IP match. Use runtime replacement for real IP. |
| `rules[].match.dst_port` | no | Destination port match. |
| `rules[].match.protocol` | no | `udp` or `tcp`. |
| `rules[].bandwidth_mbit` | no | HTB class rate. |
| `rules[].delay_ms` | no | Netem delay. |
| `rules[].jitter_ms` | no | Netem jitter paired with `delay_ms`. |
| `rules[].loss_percent` | no | Netem packet loss percent. |
| `rules[].priority` | no | HTB/filter priority; lower is higher priority. |

## Supported Modes

- `--dry-run`: print commands only.
- `--apply`: execute generated commands with rollback guard.
- `--status`: show `tc -s qdisc/class/filter`.
- `--clear`: delete root qdisc for the interface.
- `--rollback <snapshot_dir>`: currently clears the root qdisc and records the prior snapshot for audit.
- `--confirm <token>`: cancel a pending rollback guard.
- `--set-dst-ip <ip>`: runtime replacement for `JETSON_B_IP` placeholders.

## Safety Behavior

- Dry-run is the default.
- Apply requires `--apply --yes`.
- Apply and clear require root, for example `sudo python3 scripts/tc_apply.py ...`.
- Apply rejects the current SSH interface unless `--allow-ssh-interface` or `safety.allow_ssh_interface=true` is set.
- Apply requires `auto_rollback_seconds > 0`.
- The tool saves `tc` state before and after apply.

Current Jetson note: `simple` backend is verified with `sch_tbf` and `sch_netem`. `htb` backend remains a future enhancement because `sch_htb` is not enabled.
