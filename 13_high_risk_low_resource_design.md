# 13 High-Risk And Low-Resource Design

This document covers robust deployment patterns for constrained and high-risk platforms, including fixed-wing aircraft and other systems where resource use and failure behavior matter.

## Design Priorities

For high-risk operation, optimize in this order:

1. Predictable failure behavior
2. Stable latency
3. Thermal and power safety
4. Bounded CPU/RAM/storage use
5. Recoverability
6. Throughput

Do not trade away failure isolation or latency bounds for a small FPS gain unless the system owner explicitly approves the risk.

## Fixed-Wing Risk Profile

Fixed-wing systems are different from lab video benchmarks:

- vibration and motion blur can be severe
- viewpoint changes quickly
- lighting can change abruptly
- network links may be intermittent
- power and thermal budgets are fixed
- storage writes must be bounded
- a stuck perception process may affect mission safety

The inference service should be treated as a bounded component with a watchdog and a clear degraded state.

## Recommended Runtime Profile

```yaml
profile: high_risk_low_resource
runtime:
  slots: 2
  warmup_frames: 60
  fail_on_shape_mismatch: true
pipeline:
  strict_resolution: true
outputs:
  save_frames:
    enabled: false
  overlay_video:
    enabled: false
monitoring:
  metrics_interval_sec: 5
  health_interval_sec: 1
  fail:
    no_frame_timeout_sec: 2
```

Use fewer slots when RAM pressure matters more than maximum throughput. Use more slots only after measuring memory and p99 latency.

## Bounded Resource Rules

CPU:

- no Python in the production hot path
- no per-frame stdout logs
- no per-frame JSON serialization unless required
- no image encoding in the inference loop

RAM:

- preallocate frame slots
- preallocate TensorRT buffers
- avoid unbounded queues
- drop old frames rather than accumulating latency

Storage:

- use log rotation
- do not save frames by default
- write incident clips only with strict size/time limits
- keep runtime logs separate from release artifacts

GPU:

- fixed input shapes
- one TensorRT context per engine unless measured otherwise
- avoid unnecessary concurrent engines if p99 latency matters
- monitor GR3D and temperature continuously

## Watchdog And Health

The service should expose a health file or endpoint:

```json
{
  "state": "RUNNING",
  "release_id": "2026-06-06_001",
  "last_frame_age_ms": 12,
  "wall_fps": 96.4,
  "gpu_temp_c": 64.5,
  "errors_last_min": 0
}
```

Fail health when:

- last processed frame is too old
- engine errors repeat
- source reconnect budget is exhausted
- GPU temperature exceeds fail threshold
- memory usage grows continuously

## Degraded Modes

Safe degraded modes:

- stop debug output
- lower metrics detail
- stop optional recording
- switch to a backup file/source for validation
- report no-detection state when source is unavailable

Risk-changing degraded modes:

- lower resolution
- skip frames
- switch precision
- skip stage2
- reuse old detection/type over time

Risk-changing modes must be explicit in config and mission rules.

## Offline Operation

High-risk deployments should not depend on internet access.

Required local artifacts:

- engines
- configs
- class names
- calibration manifest
- acceptance report
- rollback release
- docs needed by operators

The WebUI should not load external CSS, JS, fonts, or icons.

## Operational Checklist

Before field use:

- [ ] Run startup gates.
- [ ] Run 10 minute soak.
- [ ] Confirm no thermal throttling.
- [ ] Confirm p99 latency within budget.
- [ ] Confirm health endpoint/file updates.
- [ ] Confirm watchdog restart behavior.
- [ ] Confirm rollback.
- [ ] Confirm logs rotate.
- [ ] Confirm no public network exposure.

## Agent Rules For High-Risk Profiles

Agents must stop and request approval before:

- changing resolution
- changing precision
- enabling frame skipping
- enabling network exposure
- disabling health checks
- changing fail thresholds
- increasing log volume
- adding package dependencies

Agents may perform without approval:

- read-only status checks
- config linting
- local smoke tests
- report generation
- log summarization

