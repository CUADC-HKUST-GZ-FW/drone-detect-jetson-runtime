# Drone Detect Jetson Runtime

Portable Jetson/AGX reference implementation for high-throughput YOLO video
inference, two-node streaming experiments, traffic-control experiments, and an
optional local WebUI.

This repository is intentionally source-only. Model weights, TensorRT engines,
videos, datasets, virtual environments, and benchmark outputs are ignored so
the project can be pushed to GitHub without large binary history.

## What Is Included

- Native C++ TensorRT video runners for Jetson/AGX.
- GStreamer hardware decode paths using `nvv4l2decoder` and `nvvidconv`.
- Pinned-slot C++ inference pipeline using TensorRT `enqueueV3`.
- Python helpers for YOLO smoke tests, TensorRT export, and Ultralytics engine stripping.
- Two-node sender/receiver scripts for RTP/H.264 test streams.
- JSON-to-`tc` policy tooling with dry-run, apply, status, clear, and rollback support.
- MQTT edge-agent mode for telemetry and validated remote policy updates.
- Optional FastAPI WebUI/runner services through Docker Compose.
- Unit tests for model aliasing and traffic-control command generation.

## Runtime Strategy

For production-style FPS, avoid putting Ultralytics `model.predict()` in the
frame loop. Use:

```text
video or camera source
  -> GStreamer hardware decode
  -> nvvidconv scaling before appsink
  -> C++ pinned-slot preprocessing
  -> TensorRT raw engine enqueueV3
  -> C++ timing/result handling
```

See `docs/native-trt-pipeline.md` and `docs/portable-deployment.md`.

## Safety Defaults

- `tc` defaults to dry-run.
- `apply` requires `sudo`, `--apply`, `--yes`, and auto rollback.
- The tool refuses the active SSH interface unless `--allow-ssh-interface` is passed.
- Passwords, private keys, and real node-specific env files are not stored in this repository.
- Python packages should be installed into project `.venv`; do not upgrade JetPack, CUDA, or system Python blindly.
- The WebUI can trigger privileged runner actions for `tc`; expose port `18080` only on a trusted lab network or put it behind SSH forwarding, VPN, or external authentication.

## Repository Layout

```text
native/        C++ TensorRT runners and Makefile
scripts/       setup, export, benchmark, stream, metrics, tc, and MQTT helpers
configs/       example stream and network policy configs
deploy/        public env examples and MQTT broker config
docs/          deployment, benchmark, runbook, and release notes
webui/         optional FastAPI UI and runner API
tests/         Python unit tests
assets/        local media folder; videos are ignored by Git
```

## Quick Start On A New Jetson/AGX

```bash
git clone <repo-url> drone-detect
cd drone-detect
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements-webui.txt
```

Add local artifacts without committing them:

```bash
cp /path/to/yolo26n.pt ./yolo26n.pt
mkdir -p assets models/trt
cp /path/to/test_20s.mp4 assets/test_20s.mp4
```

Build native runners:

```bash
make -C native -j"$(nproc)"
```

Export TensorRT on the target machine:

```bash
.venv/bin/python scripts/export_yolo_engine.py --model yolo26n.pt --imgsz 1024 --device 0 --half true --workspace 4
.venv/bin/python scripts/strip_ultralytics_engine.py models/trt/yolo26n_1024_fp16_ultralytics.engine --verify
```

Run native benchmark:

```bash
WARMUP=3 MEASURE=20 TARGET=1024 SLOTS=4 CAPS_W=1024 CAPS_H=576 MODE=pipeline \
  bash scripts/run_native_trt_benchmark.sh models/trt/yolo26n_1024_fp16_ultralytics.raw.engine assets/test_20s.mp4
```

## Common Commands

Inventory:

```bash
bash scripts/inventory.sh --node jetson-a
```

Baseline stream:

```bash
# Receiver first
bash scripts/start_receiver.sh --port 5000 --duration 60 --output results/baseline/received.ts

# Sender second
bash scripts/start_sender.sh --dest <JETSON_B_IP> --port 5000 --duration 60 --source testsrc
```

Metrics:

```bash
python3 scripts/collect_metrics.py --interface eth0 --duration 60 --output results/baseline/metrics.jsonl --include-tc
```

YOLO26n Python smoke test:

```bash
. .venv/bin/activate
python scripts/run_yolo_video.py --model yolov26n --source assets/test_20s.mp4 --output-dir results/yolo --device 0
```

The alias `yolov26n` resolves to `yolo26n.pt`.

Native TensorRT YOLO26n:

```bash
make -C native -j"$(nproc)"
.venv/bin/python scripts/export_yolo_engine.py --model yolo26n.pt --imgsz 1024 --device 0 --half true --workspace 4
.venv/bin/python scripts/strip_ultralytics_engine.py models/trt/yolo26n_1024_fp16_ultralytics.engine --verify
WARMUP=3 MEASURE=20 TARGET=1024 SLOTS=4 CAPS_W=1024 CAPS_H=576 MODE=pipeline \
  bash scripts/run_native_trt_benchmark.sh models/trt/yolo26n_1024_fp16_ultralytics.raw.engine assets/test_20s.mp4
```

Compose/WebUI:

```bash
cp deploy/jetson.sender.env.example deploy/jetson.sender.env
NODE_ROLE=sender HOST_PROJECT_DIR="$PWD" DRONE_INTERFACE=eth0 docker compose up -d
```

MQTT edge agent:

```bash
EDGE_NODE_ID=jetson_sender NODE_ROLE=sender MQTT_HOST=<MQTT_HOST> DRONE_INTERFACE=eth0 docker compose up -d
```

Open:

```text
http://<JETSON_IP>:18080
```

Network policy dry-run:

```bash
python3 scripts/tc_apply.py --config configs/degraded_policy.example.json --set-dst-ip <JETSON_B_IP> --dry-run
```

Network policy apply:

```bash
sudo python3 scripts/tc_apply.py --config configs/degraded_policy.example.json --set-dst-ip <JETSON_B_IP> --apply --yes --allow-ssh-interface
python3 scripts/tc_apply.py --confirm <TOKEN>
```

## Docs

- `docs/portable-deployment.md`
- `docs/artifacts.md`
- `docs/native-trt-pipeline.md`
- `docs/runbook.md`
- `docs/network-policy-schema.md`
- `docs/experiment-report.md`
- `docs/github-release-checklist.md`

## GitHub Readiness

Before pushing:

```bash
python3 -m pytest
git ls-files | grep -E '\.(pt|onnx|engine|raw\.engine|mp4|zip|tar|gz)$' && exit 1 || true
```

Model weights, TensorRT engines, and videos should be published through
GitHub Releases, Git LFS, object storage, or a private artifact store. See
`docs/artifacts.md`.

## License

This repository is MIT licensed. Third-party runtimes, including NVIDIA
JetPack/TensorRT and Ultralytics, have their own licenses and deployment terms.
