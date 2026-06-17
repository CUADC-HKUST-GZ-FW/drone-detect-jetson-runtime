# MQTT Edge Agent

`scripts/edge_mqtt_agent.py` connects each Jetson to the cloud MQTT broker.
It publishes telemetry, subscribes to validated network configs, applies them
through `scripts/tc_apply.py`, and publishes ACK messages.

## Topics

For the current two-Jetson demo:

```text
6g/edge/jetson_01/telemetry
6g/edge/jetson_01/config
6g/edge/jetson_01/ack

6g/edge/jetson_02/telemetry
6g/edge/jetson_02/config
6g/edge/jetson_02/ack
```

## Compose

Start Jetson A:

```bash
cd /opt/drone-detect
cp deploy/jetson.sender.env.example .env
docker compose up -d
```

Start Jetson B:

```bash
cd /opt/drone-detect
cp deploy/jetson.receiver.env.example .env
docker compose up -d
```

The `drone-edge-agent` service runs in the existing privileged host-network
container profile so it can apply `tc` without relying on host-user sudo.
Telemetry includes parsed qdisc counters by default. Set
`EDGE_TELEMETRY_INCLUDE_RAW_QDISC=1` only when full `tc -s qdisc` text is
needed for debugging.

## Config Message

Publish to `6g/edge/<node_id>/config`:

```json
{
  "request_id": "verify-20260616-001",
  "node_id": "jetson_01",
  "validated_by": "oai_verify_twin",
  "target": {
    "interface": "eth0",
    "service": "uav_fire_video",
    "direction": "egress",
    "dst_ip": "192.0.2.20",
    "dst_port": 5000,
    "protocol": "udp"
  },
  "tc": {
    "action": "replace",
    "backend": "simple",
    "rate_mbps": 20,
    "delay_ms": 10,
    "jitter_ms": 2,
    "loss_percent": 0.1,
    "duration_s": 60
  }
}
```

Set `"dry_run": true` inside `tc` to validate command generation without
changing qdisc state.
The default backend is `simple`, which applies the impairment to interface
egress. Use `"backend": "htb"` when the server wants the generated policy to
include `dst_ip`/`dst_port`/`protocol` filters.

## Safety

- Configs are converted to temporary policy files under
  `results/mqtt_agent/policies/`.
- Real apply uses `tc_apply.py --apply --yes --auto-rollback-seconds`.
- `tc.duration_s` controls the rollback guard window.
- ACK messages include the return code, command output, policy path, and
  rollback token when a real apply starts.
