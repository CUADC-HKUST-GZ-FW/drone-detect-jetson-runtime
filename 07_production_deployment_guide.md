# 07 Production Deployment Guide

This document turns the training, export, and benchmark work into a deployable Jetson YOLO service.

It is written for developers and agents that need to ship a stable high-performance pipeline, not just run a benchmark once.

## Deployment Goal

The production system should:

- load known model artifacts only
- preserve the declared input resolution policy
- use TensorRT C++ inference for production throughput
- use NVIDIA GStreamer decode/scale paths when the source is video
- record enough metrics to diagnose performance, thermal, and accuracy regressions
- fail closed when critical startup validation fails
- support rollback without rebuilding engines on the device

## Recommended Runtime Layout

Use one release directory per deployable version:

```text
/opt/yolo-pipeline/
  current -> releases/2026-06-06_001/
  previous -> releases/2026-06-05_003/
  releases/
    2026-06-06_001/
      bin/
        yolo_pipeline_runner
      config/
        pipeline_config.yaml
        model_manifest.yaml
      engines/
        stage1_yolo26n_1024_fp16.raw.engine
        stage2_yolo26n_requested400_actual416_fp16.raw.engine
      metadata/
        engine_metadata_stage1.json
        engine_metadata_stage2.json
        dataset_manifest.json
        calibration_manifest.json
        benchmark_summary.json
      docs/
        release_acceptance_report.md
      logs/
```

For development on the current Jetson, the benchmark directories remain useful:

```bash
~/jetson_benchmark_assets/
~/jetson_90fps_yolo26n1024/
~/jetson_cascade_benchmark/
~/jetson_wallfps_optimization/
```

Do not use a loose pile of `.pt`, `.engine`, and scripts as a production release. Build a versioned release folder and make `current` point to it after validation.

## Artifact Contract

Each production release must include:

- PyTorch source model, if available: `*.pt`
- Ultralytics engine, if used for validation: `*.engine`
- raw TensorRT plan for C++ runner: `*.raw.engine`
- engine metadata JSON extracted from Ultralytics prefix
- model manifest with class names, requested size, actual size, precision, and export command
- calibration manifest for INT8 engines
- benchmark summary for target Jetson
- runtime config
- acceptance report

Minimum engine metadata fields:

```yaml
model_id: yolo26n_custom_1024_fp16
source_model: models/best.pt
engine_path: engines/yolo26n_custom_1024_fp16.raw.engine
requested_imgsz: [1024, 1024]
actual_imgsz: [1024, 1024]
precision: fp16
task: detect
num_classes: 3
names:
  0: person
  1: car
  2: truck
export_host:
  device: Jetson Orin NX Super
  l4t: R36.5
  tensorrt: "10.3.x"
```

For requested `400`, record the true exported shape:

```yaml
requested_imgsz: [400, 400]
actual_imgsz: [416, 416]
shape_alias: requested400_actual416
```

## Resolution Policy

The current user requirement is strict `1024x1024` for the first-stage full-frame model.

Production code must check:

- engine input shape is `[1,3,1024,1024]`
- appsink/C++ frame is `1024x1024`
- padding policy matches YOLO letterbox behavior
- no `1024x576` path is reported as strict `1024x1024`

For 16:9 sources, use a square canvas:

```text
decode 1080p
  -> scale content to 1024x576
  -> composite/pad into 1024x1024
  -> appsink BGR 1024x1024
  -> TensorRT input 1024x1024
```

For cascade stage2, keep the naming explicit:

```text
requested400_actual416
```

## Startup Validation Gates

The service should run these checks before processing frames.

Hard-fail gates:

- raw TensorRT engine file exists and is readable
- TensorRT can deserialize the engine
- engine input and output tensor names match config
- actual engine input size matches config
- class names in model manifest match postprocess config
- input video/camera source can open
- GStreamer pipeline can preroll
- CUDA device is visible
- output directory or sink is writable, if enabled

Warn-only gates:

- DeepStream is not installed
- DLA is visible but not configured
- `trtexec --version` is unavailable
- camera is absent when file/video mode is configured
- tegrastats parser cannot parse one optional metric

Do not continue if a hard-fail gate fails. Write a structured startup error and exit non-zero so systemd can restart or mark the service failed.

## Recommended Single-Model Runtime

```text
filesrc/camerasrc
  -> parser/demux
  -> nvv4l2decoder
  -> nvvidconv
  -> nvcompositor for strict square canvas
  -> appsink
  -> C++ preallocated frame slot
  -> CUDA H2D/preprocess
  -> TensorRT enqueueV3
  -> output parse/NMS
  -> result sink
```

Production defaults:

- `slots=4`
- `appsink drop=true sync=false max-buffers=4`
- no per-frame image saving
- no per-frame drawing unless an explicit debug output is enabled
- no per-frame stdout logging
- one JSON metrics event per interval, not per frame

## Recommended Cascade Runtime

```text
frame N:
  stage1 detects location only
  selected bbox creates ROI crop
  stage2 classifies/detects concrete type
```

Pipeline parallel form:

```text
stage1(frame N+1) overlaps stage2(frame N)
```

This improves throughput but does not make stage2 available before stage1 for the same frame.

The current measured results are:

```text
800 + requested400_actual416 pipeline:  about 113 FPS
1024 + requested400_actual416 pipeline: about 87.5 FPS
strict 1024 single-model C++ path:      about 103 FPS
```

If the product requirement is strict `1024x1024`, treat the `1024 + requested400_actual416` result as the relevant cascade baseline.

## Service Management

Use a systemd unit only after the command has passed local foreground validation.

Recommended lifecycle:

1. Build a versioned release directory.
2. Run startup validation directly in a shell.
3. Run a 60 second foreground smoke test.
4. Run a 10 minute thermal/performance soak test.
5. Update `current` symlink.
6. Restart systemd service.
7. Verify health endpoint and logs.

Example unit template:

```text
templates/systemd/yolo-pipeline.service
```

## Rollback

Rollback should not rebuild anything.

Required rollback state:

- previous release directory
- previous raw engines
- previous runtime config
- previous model manifest
- previous acceptance report

Rollback command pattern:

```bash
sudo systemctl stop yolo-pipeline
sudo ln -sfn /opt/yolo-pipeline/releases/2026-06-05_003 /opt/yolo-pipeline/current
sudo systemctl start yolo-pipeline
sudo systemctl status yolo-pipeline --no-pager
```

After rollback, run the startup validation report again and save it with the incident notes.

## Degraded Modes

Degraded modes must be explicit in config and logs.

Acceptable examples:

- disable debug output sink
- lower result publication rate
- skip non-critical result serialization fields
- use file input instead of camera during camera outage

Quality-changing degraded modes require product approval:

- lower first-stage resolution
- switch FP16 to INT8
- skip frames
- run stage2 less often
- track and reuse type labels across frames

## Security And Access

Production service guidance:

- run as a non-root service user when possible
- do not store SSH keys or credentials in runtime config
- do not log full environment variables
- keep model/config directories read-only to the service account
- keep writable logs under a dedicated directory
- avoid serving debug frames on public interfaces

## Production Readiness Definition

A release is production-ready only when:

- model accuracy is validated on held-out task data
- TensorRT output is compared against PyTorch or a trusted reference
- target-resolution benchmark is recorded
- 10 minute soak shows no thermal collapse
- startup gates pass
- logs and metrics are parseable
- rollback is tested
- known limitations are written in the acceptance report

