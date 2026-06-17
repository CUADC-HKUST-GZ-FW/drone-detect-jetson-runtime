# 08 Runtime Config Templates

This document defines the configuration style for a deployable Jetson YOLO pipeline.

The goal is to let developers and agents change runtime behavior through reviewed config files, not source edits.

Template files:

```text
templates/pipeline_config.example.yaml
templates/model_manifest.example.yaml
templates/log_schema.json
templates/metrics_schema.md
templates/acceptance_report_template.md
templates/systemd/yolo-pipeline.service
```

## Config Principles

- Keep all paths absolute in production.
- Keep requested and actual model sizes separate.
- Use one model manifest per release.
- Use one runtime config per service instance.
- Do not hide quality-changing options behind generic names.
- Fail startup if config disagrees with engine metadata.
- Record every non-default runtime option in the report.

## Required Runtime Sections

```yaml
app:
  name: yolo-pipeline
  release_id: 2026-06-06_001
  mode: production

runtime:
  device: cuda:0
  precision_policy: fp16
  strict_resolution: true
  warmup_frames: 120
  slots: 4

source:
  kind: file
  uri: /home/jetson/jetson_benchmark_assets/videos/benchmark_5min_1080p30_coco_val2017_synthetic.mp4
  expected_width: 1920
  expected_height: 1080
  expected_fps: 30

pipeline:
  input_canvas_width: 1024
  input_canvas_height: 1024
  letterbox_value: 114
  gstreamer:
    use_hw_decode: true
    decoder: nvv4l2decoder
    converter: nvvidconv
    compositor: nvcompositor

models:
  stage1:
    id: yolo26n_1024_fp16
    engine: /opt/yolo-pipeline/current/engines/yolo26n_1024_fp16.raw.engine
    requested_imgsz: [1024, 1024]
    actual_imgsz: [1024, 1024]
    precision: fp16
  stage2:
    enabled: true
    id: yolo26n_requested400_actual416_fp16
    engine: /opt/yolo-pipeline/current/engines/yolo26n_requested400_actual416_fp16.raw.engine
    requested_imgsz: [400, 400]
    actual_imgsz: [416, 416]
    precision: fp16

postprocess:
  conf_threshold: 0.25
  iou_threshold: 0.70
  max_detections: 300

monitoring:
  tegrastats: true
  metrics_interval_sec: 5
  health_interval_sec: 2
```

## Model Manifest

The model manifest is immutable for a release.

It should answer:

- which model was trained
- on which dataset
- with which class mapping
- how it was exported
- what engine shape was produced
- what validation proved it safe enough

Minimum fields:

```yaml
release_id: 2026-06-06_001
models:
  - id: yolo26n_1024_fp16
    role: stage1_location
    task: detect
    source_pt: models/best.pt
    raw_engine: engines/yolo26n_1024_fp16.raw.engine
    requested_imgsz: [1024, 1024]
    actual_imgsz: [1024, 1024]
    precision: fp16
    class_names:
      0: target
    export:
      command: yolo export model=models/best.pt format=engine imgsz=1024 half=True device=0
      host: jetson-orin-nx-super
      l4t: R36.5
      tensorrt: "10.3.x"
    validation:
      pytorch_map50_95: null
      tensorrt_map50_95: null
      benchmark_fps: 103.0
```

## Config Validation Rules

Startup should reject:

- missing engine path
- missing model id
- missing class names
- config `actual_imgsz` that differs from engine binding shape
- stage2 enabled without a stage2 engine
- strict `1024x1024` mode with a non-square appsink target
- requested `400` reported as actual `400` when metadata says `416`
- INT8 engine without calibration manifest

Startup may warn:

- benchmark source is synthetic COCO-val video
- DeepStream is absent
- DLA is not used
- model accuracy fields are null in a development release

## Agent Editing Rules

Agents may edit:

- thresholds
- slots
- source URI
- log directories
- debug output enable/disable

Agents must not silently edit:

- class id order
- engine paths
- actual input sizes
- precision
- letterbox policy
- cascade enabled/disabled
- quality-changing degraded modes

When an agent changes a config, it should write a short change note:

```text
changed_by: agent
reason: "Switch source from synthetic video to RTSP camera for field smoke test."
expected_effect: "No model or engine change."
validation_required: "Run startup gates and 60 second smoke test."
```

## Runtime Profiles

Use named profiles instead of ad hoc edits.

```yaml
profiles:
  benchmark:
    save_frames: false
    draw_overlay: false
    metrics_interval_sec: 1
  production:
    save_frames: false
    draw_overlay: false
    metrics_interval_sec: 5
  debug:
    save_frames: true
    draw_overlay: true
    metrics_interval_sec: 1
```

The production profile should never enable per-frame logs or image saves by default.

