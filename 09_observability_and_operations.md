# 09 Observability And Operations

This document defines what the Jetson YOLO pipeline must log, measure, and alert on.

## Observability Goals

A production run should make these questions answerable:

- Is the service alive?
- Is the video source flowing?
- Is TensorRT inference running on GPU?
- Did FPS or latency regress?
- Is the device thermally throttling?
- Is power mode or clocks wrong?
- Are detections missing because the model changed, the camera changed, or preprocessing changed?
- Can the release be rolled back safely?

## Metric Groups

Frame pipeline:

- frames_read
- frames_processed
- frames_failed
- source_fps
- wall_fps
- end_to_end_latency_ms
- read_ms
- preprocess_ms
- infer_ms
- postprocess_ms
- publish_ms

Cascade:

- stage1_infer_ms
- stage1_detections
- stage1_selected_conf
- roi_area_ratio
- stage2_infer_ms
- stage2_class
- stage2_conf
- fallback_count

Jetson:

- GR3D_FREQ avg/max
- CPU utilization avg/max
- RAM used avg/max
- EMC frequency, if available
- GPU temperature avg/max
- CPU temperature avg/max
- VDD_IN power avg/max

Service:

- uptime_sec
- release_id
- config_hash
- engine_hash
- restart_count
- health_state

## Structured Log Event

Use JSON Lines for machine parsing:

```json
{
  "ts": "2026-06-06T10:00:00+08:00",
  "level": "INFO",
  "event": "metrics",
  "release_id": "2026-06-06_001",
  "source": "camera0",
  "wall_fps": 101.7,
  "latency_ms_p50": 9.4,
  "latency_ms_p99": 14.8,
  "gr3d_avg_pct": 82.1,
  "gpu_temp_c_max": 67.5,
  "vdd_in_w_avg": 18.2
}
```

Do not print one verbose line per frame during production. It destroys wall FPS and makes incidents harder to inspect.

## Health States

Use a small state machine:

```text
STARTING
  -> VALIDATING
  -> RUNNING
  -> DEGRADED
  -> FAILED
  -> STOPPING
```

Hard failure examples:

- engine cannot deserialize
- source cannot open
- engine shape does not match config
- CUDA context creation fails
- output sink required by config is unavailable

Degraded examples:

- metrics sink unavailable
- optional debug output disabled
- temporary source reconnect is in progress

## Tegrastats Collection

Run one tegrastats process per benchmark or service instance:

```bash
tegrastats --interval 1000 --logfile /var/log/yolo-pipeline/tegrastats.log
```

For benchmark runs, file names should include:

```text
model_precision_resolution_source_mode_timestamp.log
```

The parser should tolerate missing fields. Jetson tegrastats output can vary across Jetson Linux releases and power modes.

Minimum parser output:

```json
{
  "gr3d_avg_pct": 81.2,
  "gr3d_max_pct": 99.0,
  "ram_used_mb_avg": 5620,
  "ram_used_mb_max": 6104,
  "gpu_temp_c_avg": 63.1,
  "gpu_temp_c_max": 68.0,
  "cpu_temp_c_avg": 58.4,
  "cpu_temp_c_max": 64.0,
  "vdd_in_w_avg": 17.8,
  "vdd_in_w_max": 22.3
}
```

## Suggested SLOs

Example targets for the current Jetson Orin NX Super work:

```yaml
single_model_strict_1024:
  wall_fps_min: 90
  p99_latency_ms_max: 25

cascade_1024_requested400_actual416:
  wall_fps_min: 80
  p99_latency_ms_max: 40

thermal:
  gpu_temp_c_warn: 75
  gpu_temp_c_fail: 85
```

Tune these for the real camera, model, and enclosure. Synthetic COCO-val video is stable for reproducibility but is not a substitute for field video.

## Alert Conditions

Warn:

- wall FPS drops below SLO for 60 seconds
- GR3D drops to near idle while frames are expected
- VDD_IN is far below known benchmark power during load
- GPU temp exceeds warning threshold
- fallback_count increases above baseline
- source reconnect occurred

Fail:

- no frames processed for configured timeout
- repeated engine inference errors
- GPU temp exceeds fail threshold
- source reconnect loop exceeds retry budget
- config/engine validation fails after restart

## Operational Triage

FPS regression:

1. Compare release id and config hash.
2. Check whether input source changed.
3. Check GR3D, clocks, and temperature.
4. Check whether debug output or per-frame logging is enabled.
5. Compare stage timing breakdown.
6. Re-run a known synthetic video benchmark.

Accuracy regression:

1. Save example frames.
2. Confirm model manifest and class names.
3. Confirm preprocessing resolution and letterbox value.
4. Compare PyTorch and TensorRT output on selected frames.
5. Check camera viewpoint, lighting, motion blur, and object scale drift.
6. Add hard examples to the next training set.

Thermal regression:

1. Confirm fan and enclosure airflow.
2. Confirm power mode and jetson_clocks state.
3. Compare VDD_IN and GR3D against previous release.
4. Run a 10 minute soak test.
5. Do not hide thermal throttling by shortening the benchmark.

## Data Drift And Retraining Triggers

Start a retraining review when:

- false positives increase in a new scene
- false negatives increase for a class
- lighting/weather/camera angle changed
- new object subtype appears
- stage2 crop quality differs from training crops
- operator overrides or manual corrections cluster around the same failure mode

Retraining data should include:

- raw frame
- production crop
- model prediction
- corrected label
- source/camera id
- timestamp
- release id

