# 05 Agent Runbook

This runbook is for future agents operating on the Jetson.

## First Rule

Inspect current state before assuming previous results still apply.

```bash
ls -lh ~/jetson_90fps_yolo26n1024/
ls -lh ~/jetson_cascade_benchmark/
cat /etc/nv_tegra_release
```

## Performance Mode

Do not guess power mode ids. Inspect first:

```bash
sudo nvpmodel -q --verbose
sudo jetson_clocks --show
```

Apply clocks if needed:

```bash
sudo jetson_clocks
```

## Check Engine Metadata

```bash
python3 - <<'PY'
from pathlib import Path
import struct, json
p = Path("model.engine")
data = p.read_bytes()
n = struct.unpack("<I", data[:4])[0]
print(json.dumps(json.loads(data[4:4+n]), indent=2))
PY
```

Verify:

- `imgsz`
- `half`
- `int8`
- `end2end`
- class names

## Create Raw TensorRT Plan

```bash
python3 - <<'PY'
from pathlib import Path
import struct, json
p = Path("model.engine")
data = p.read_bytes()
n = struct.unpack("<I", data[:4])[0]
Path("model.raw.engine").write_bytes(data[4+n:])
print(json.loads(data[4:4+n])["imgsz"])
PY
```

## Export Missing Engine

```bash
source ~/venvs/yolo-jetson/bin/activate
yolo export \
  task=detect \
  model=~/jetson_benchmark_assets/models/yolo26n.pt \
  format=engine \
  imgsz=1024 \
  half=True \
  device=0 \
  workspace=4 \
  verbose=False
```

If exporting requested `400`, expect actual `416`:

```bash
yolo export model=... format=engine imgsz=400 half=True device=0
```

Record the warning and name the engine:

```text
yolo26n_requested400_actual416_fp16.engine
```

## Run Single-Model Strict 1024 Benchmark

```bash
cd ~/jetson_90fps_yolo26n1024
(tegrastats --interval 1000 --logfile tegrastats/strict1024.log >/dev/null 2>&1 & echo $! > logs/tegrastats.pid)
scripts/native_trt_video_strict_square_runner \
  engines/yolo26n_1024_fp16.raw.engine \
  ~/jetson_benchmark_assets/videos/benchmark_5min_1080p30_coco_val2017_synthetic.mp4 \
  5 60 1024 4 1024 576 \
  > logs/strict1024.json 2> logs/strict1024.stderr
kill "$(cat logs/tegrastats.pid)" 2>/dev/null || true
```

## Run Cascade Benchmark

```bash
cd ~/jetson_cascade_benchmark

# 800 + requested400_actual416
scripts/cascade_trt_pipeline_runner \
  engines/yolo26n_800_fp16.raw.engine \
  engines/yolo26n_requested400_actual416_fp16.raw.engine \
  ~/jetson_benchmark_assets/videos/benchmark_5min_1080p30_coco_val2017_synthetic.mp4 \
  800 416 5 60 4 4 \
  > logs/cascade_800_416_pipe.json 2> logs/cascade_800_416_pipe.stderr

# 1024 + requested400_actual416
scripts/cascade_trt_pipeline_runner \
  engines/yolo26n_1024_fp16.raw.engine \
  engines/yolo26n_requested400_actual416_fp16.raw.engine \
  ~/jetson_benchmark_assets/videos/benchmark_5min_1080p30_coco_val2017_synthetic.mp4 \
  1024 416 5 60 4 4 \
  > logs/cascade_1024_416_pipe.json 2> logs/cascade_1024_416_pipe.stderr
```

Always wrap final runs with tegrastats.

## Report Requirements

Every report must include:

- requested model sizes
- actual engine sizes
- precision
- strict/non-strict resolution policy
- exact video source
- warmup/measurement duration
- FPS
- mean/p90/p99 latency
- stage timing breakdown
- GR3D avg/max
- GPU/CPU temp max
- VDD_IN avg/max
- fallback count for cascade
- whether stage2 type parsing is included

## Agent Warnings

- Do not call a `416` engine `400`.
- Do not report `1024x576` appsink as strict `1024x1024`.
- Do not confuse throughput FPS with single-frame latency.
- Do not use Ultralytics Python FPS as production C++ FPS.
- Do not install DeepStream unless explicitly requested.
- Do not switch to INT8 unless calibration and quality validation are part of the task.
- Do not change nvpmodel mode id without inspecting available modes.

## Current Result Summary

Single model:

```text
strict 1024 C++ TensorRT: about 103 FPS
```

Cascade:

```text
800 + requested400_actual416 pipeline:  about 113 FPS
1024 + requested400_actual416 pipeline: about 87.5 FPS
```
