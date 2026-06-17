# Jetson Orin NX YOLO26n TensorRT Pipeline

Reusable Jetson Orin NX YOLO26n acceleration package with documentation, a lightweight WebUI, C++ TensorRT/GStreamer runner sources, deployment templates, and sanitized benchmark summaries.

It covers two connected workflows:

1. Build or fine-tune a YOLO model from a custom training set.
2. Deploy the trained model into a high performance Jetson C++/TensorRT/GStreamer pipeline.

Current tested deployment context:

- Device: NVIDIA Jetson Orin NX Super
- Jetson Linux: R36.5
- Main runtime stack: CUDA, TensorRT 10.3, GStreamer NVIDIA plugins, C++ TensorRT runners
- Primary model used in benchmarks: `yolo26n`
- Best single-model strict `1024x1024` path: about `103 FPS`
- Best cascaded path:
  - `800 + requested400_actual416`: about `113 FPS`
  - `1024 + requested400_actual416`: about `87.5 FPS`

Important naming note:

- User-facing "400x400" YOLO export becomes `416x416` for this YOLO model because max stride is 32.
- Do not silently call it a true 400 engine. Use `requested400_actual416` in scripts and reports.

## Repository Contents

- `webui/`: dependency-free Python standard-library WebUI and API for local or token-protected Jetson operations.
- `native/`: C++ TensorRT runner sources and a Jetson-oriented Makefile.
- `templates/`: production config, model manifest, log schema, metrics schema, and systemd templates.
- `reports/`: sanitized benchmark summaries from the Jetson Orin NX optimization work.
- `scripts/`: benchmark summarization and wall-FPS experiment helpers.
- `ARTIFACTS.md`: policy for engines, weights, videos, logs, and release artifacts that must stay out of git.

This repository intentionally does not include model weights, TensorRT engines, videos, raw logs, tegrastats captures, or compiled C++ binaries.

## Quick Start

Run the WebUI locally on a Jetson:

```bash
cd webui
python3 server.py --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

Build the native C++ runners on the target Jetson:

```bash
make -C native
```

For remote access to the WebUI, set `JETSON_WEBUI_TOKEN` or use SSH forwarding. The server refuses non-loopback binds without a token by default.

## Documents

- [01 Dataset And Fine-Tuning](01_dataset_and_finetuning.md)
- [02 Export And Validation](02_export_and_validation.md)
- [03 High Performance C++ Pipeline](03_high_performance_cpp_pipeline.md)
- [04 Cascaded Detection Pipeline](04_cascade_detection_pipeline.md)
- [05 Agent Runbook](05_agent_runbook.md)
- [06 Troubleshooting And Checklists](06_troubleshooting_and_checklists.md)
- [07 Production Deployment Guide](07_production_deployment_guide.md)
- [08 Runtime Config Templates](08_runtime_config_templates.md)
- [09 Observability And Operations](09_observability_and_operations.md)
- [10 Release Acceptance Checklist](10_release_acceptance_checklist.md)
- [11 Lightweight WebUI Service](11_lightweight_webui_service.md)
- [12 Service Deployment And Versioning](12_service_deployment_and_versioning.md)
- [13 High-Risk And Low-Resource Design](13_high_risk_low_resource_design.md)

## Templates

- [Pipeline config example](templates/pipeline_config.example.yaml)
- [Model manifest example](templates/model_manifest.example.yaml)
- [Log schema](templates/log_schema.json)
- [Metrics schema](templates/metrics_schema.md)
- [Acceptance report template](templates/acceptance_report_template.md)
- [systemd service template](templates/systemd/yolo-pipeline.service)
- [WebUI service](webui/README.md)
- [WebUI API](webui/API.md)
- [WebUI systemd template](webui/systemd/jetson-yolo-webui.service)
- [Deployable WebUI env example](webui/deploy/jetson-yolo-webui.env.example)
- [Deployable WebUI systemd unit](webui/deploy/jetson-yolo-webui.service)
- [Deployable WebUI healthcheck service](webui/deploy/jetson-yolo-webui-healthcheck.service)
- [Deployable WebUI healthcheck timer](webui/deploy/jetson-yolo-webui-healthcheck.timer)
- [Deployable WebUI access configurator](webui/deploy/configure_access.sh)
- [Deployable WebUI verifier](webui/deploy/verify_deployment.sh)
- [Native runner build notes](native/README.md)
- [Benchmark report notes](reports/README.md)
- [Artifact policy](ARTIFACTS.md)

## Production Deployment Package

A production-ready release should contain:

- raw TensorRT engines
- extracted engine metadata
- immutable model manifest
- runtime config
- benchmark and tegrastats summaries
- acceptance report
- rollback target

Use the production guide and templates before moving from benchmark scripts to a long-running service.

## Current Jetson Result Paths

Single-model optimization:

```bash
~/jetson_90fps_yolo26n800/
~/jetson_90fps_yolo26n1024/
~/jetson_wallfps_optimization/
```

Cascaded benchmark:

```bash
~/jetson_cascade_benchmark/
~/jetson_wallfps_optimization/cascade/
```

Benchmark assets:

```bash
~/jetson_benchmark_assets/
```

## Core Principles

- Train on a sufficiently powerful GPU workstation when possible; use Jetson for target export, validation, and deployment benchmarking.
- Always validate `torch.cuda.is_available()` when using PyTorch on Jetson.
- Build TensorRT engines on the target Jetson or with exactly matching TensorRT/CUDA versions.
- Keep inference resolution, precision, preprocessing, and postprocessing explicit in every report.
- Keep requested and actual engine sizes separate.
- For Jetson throughput, avoid Ultralytics `predict()` loops in production. Use C++ TensorRT with preallocated buffers.
- Use GStreamer/NVIDIA decode and scaling before CPU appsink whenever possible.
- Record tegrastats for GPU utilization, temperatures, RAM, and power.
- Do not treat a synthetic COCO-val stream as a real camera validation result.
- Do not ship a release without a rollback path.

## Official References

- Ultralytics custom training and dataset docs: https://docs.ultralytics.com/modes/train/
- Ultralytics dataset format docs: https://docs.ultralytics.com/datasets/
- Ultralytics export docs: https://docs.ultralytics.com/modes/export/
- NVIDIA TensorRT documentation: https://docs.nvidia.com/deeplearning/tensorrt/
- NVIDIA Jetson Linux and multimedia docs: https://docs.nvidia.com/jetson/
- NVIDIA Accelerated GStreamer guide for Jetson: https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/SD/Multimedia/AcceleratedGstreamer.html
