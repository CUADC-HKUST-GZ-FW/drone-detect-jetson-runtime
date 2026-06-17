# Portable Deployment Guide

This guide moves the project from one Jetson/AGX setup to another without
copying host-specific state.

## 1. Clone And Prepare

```bash
git clone <repo-url> drone-detect
cd drone-detect
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements-webui.txt
python -m pip install pytest
```

Install the Jetson runtime stack through NVIDIA JetPack. Do not upgrade CUDA,
TensorRT, or system Python blindly on a working JetPack image.

## 2. Add Local Artifacts

Copy model weights and test media outside Git history:

```bash
cp /path/to/yolo26n.pt ./yolo26n.pt
mkdir -p assets models/trt
cp /path/to/test_20s.mp4 assets/test_20s.mp4
```

See `docs/artifacts.md` for artifact policy.

## 3. Build Native C++ Runners

```bash
make -C native -j"$(nproc)"
```

Required system libraries:

- CUDA headers and runtime
- TensorRT headers and runtime
- OpenCV with GStreamer support
- GStreamer NVIDIA plugins

## 4. Export TensorRT On The Target

```bash
.venv/bin/python scripts/export_yolo_engine.py \
  --model yolo26n.pt \
  --imgsz 1024 \
  --device 0 \
  --half true \
  --workspace 4

.venv/bin/python scripts/strip_ultralytics_engine.py \
  models/trt/yolo26n_1024_fp16_ultralytics.engine \
  --verify
```

Do not reuse `.engine` files built on another Jetson/AGX unless the runtime
image and hardware are intentionally identical.

## 5. Run Native TensorRT Benchmark

Fast 16:9 path:

```bash
WARMUP=3 MEASURE=20 TARGET=1024 SLOTS=4 CAPS_W=1024 CAPS_H=576 MODE=pipeline \
  bash scripts/run_native_trt_benchmark.sh \
  models/trt/yolo26n_1024_fp16_ultralytics.raw.engine \
  assets/test_20s.mp4
```

Strict square path:

```bash
WARMUP=3 MEASURE=20 TARGET=1024 SLOTS=4 CAPS_W=1024 CAPS_H=576 MODE=strict \
  bash scripts/run_native_trt_benchmark.sh \
  models/trt/yolo26n_1024_fp16_ultralytics.raw.engine \
  assets/test_20s.mp4
```

Collect final runs with:

```bash
tegrastats --interval 1000 --logfile results/tegrastats.log
```

## 6. Configure Two-Node Demo

Create local env files from examples:

```bash
cp deploy/jetson.sender.env.example deploy/jetson.sender.env
cp deploy/jetson.receiver.env.example deploy/jetson.receiver.env
```

Edit:

- `EDGE_NODE_ID`
- `NODE_ROLE`
- `MQTT_HOST`
- `DRONE_INTERFACE`
- `HOST_PROJECT_DIR`

Keep real `.env` files out of Git.

## 7. Safety Checks

Before applying network shaping:

```bash
python3 scripts/tc_apply.py --config configs/degraded_policy.example.json --set-dst-ip <receiver-ip> --dry-run
```

Only apply on a lab network after verifying the interface:

```bash
sudo python3 scripts/tc_apply.py \
  --config configs/degraded_policy.example.json \
  --set-dst-ip <receiver-ip> \
  --apply --yes --allow-ssh-interface
```

The default public examples use `EDGE_TC_DRY_RUN_ONLY=1`.
