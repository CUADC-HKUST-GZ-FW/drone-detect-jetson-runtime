# 02 Export And Validation

This document covers exporting a fine-tuned YOLO model to TensorRT and validating it on Jetson.

## Export Principles

- Export on the target Jetson whenever possible.
- Keep TensorRT/CUDA/Ultralytics versions stable between export and deployment.
- Export one engine per static input size.
- Record requested and actual input size.
- Record precision: FP32, FP16, INT8.
- Do not include engine build time in inference FPS.

## Environment

Activate the tested environment:

```bash
source ~/venvs/yolo-jetson/bin/activate
```

Check CUDA/PyTorch:

```bash
python - <<'PY'
import torch
print("torch", torch.__version__)
print("cuda available", torch.cuda.is_available())
if torch.cuda.is_available():
    print(torch.cuda.get_device_name(0))
PY
```

## Export FP16 Engine

Example for `1024x1024`:

```bash
yolo export \
  task=detect \
  model=/path/to/best.pt \
  format=engine \
  imgsz=1024 \
  half=True \
  device=0 \
  workspace=4 \
  verbose=False
```

Example for stage2 requested `400`:

```bash
yolo export \
  task=detect \
  model=/path/to/stage2_best.pt \
  format=engine \
  imgsz=400 \
  half=True \
  device=0 \
  workspace=4 \
  verbose=False
```

Expected behavior for the tested YOLO26n model:

```text
WARNING: imgsz=[400] must be multiple of max stride 32, updating to [416]
```

If this happens, name the engine:

```text
stage2_requested400_actual416_fp16.engine
```

## Export INT8 Engine

Only use INT8 when calibration and accuracy are acceptable.

```bash
yolo export \
  model=/path/to/best.pt \
  format=engine \
  imgsz=1024 \
  int8=True \
  data=/path/to/calibration.yaml \
  device=0
```

INT8 may improve throughput but can reduce accuracy. It should not be used when the requirement is "do not lower inference quality" unless validation proves equivalence for the task.

## Ultralytics Engine Metadata Prefix

Ultralytics `.engine` files include a metadata prefix before the raw TensorRT plan.

For `trtexec` or low-level TensorRT C++ loading, strip the prefix:

```python
from pathlib import Path
import json
import struct

p = Path("model.engine")
data = p.read_bytes()
n = struct.unpack("<I", data[:4])[0]
metadata = json.loads(data[4:4+n])
Path("model.raw.engine").write_bytes(data[4+n:])
print(metadata)
```

Use `.engine` with Ultralytics. Use `.raw.engine` with direct TensorRT C++ runners.

## Validate Engine Shape

Use metadata:

```bash
python inspect_engine_metadata.py
```

Or use TensorRT:

```bash
/usr/src/tensorrt/bin/trtexec \
  --loadEngine=model.raw.engine \
  --duration=5 \
  --warmUp=500 \
  --useCudaGraph \
  --noDataTransfers
```

For the tested 1024 engine:

```text
input:  images, shape [1,3,1024,1024], DataType.FLOAT
output: output0, shape [1,300,6]
```

## Runtime Validation

Minimal Python validation:

```bash
yolo predict \
  model=/path/to/model.engine \
  source=/path/to/image.jpg \
  imgsz=1024 \
  device=0 \
  save=False \
  verbose=False
```

C++ validation:

```bash
./native_trt_video_pipeline_runner \
  model.raw.engine \
  video.mp4 \
  5 60 1024 4
```

## Benchmark Rules

Always report:

- model name
- requested input size
- actual input size
- precision
- engine path
- video source
- warmup seconds
- measurement seconds
- frames processed
- wall FPS
- latency mean/p90/p99
- tegrastats GR3D avg/max
- GPU/CPU temperature max
- VDD_IN avg/max

Do not report:

- engine build time as inference time
- PyTorch FPS as TensorRT FPS
- requested size when actual engine size differs
- Ultralytics Python path as production C++ throughput

## Accuracy Validation After Export

Recommended:

```bash
yolo val \
  model=/path/to/model.engine \
  data=/path/to/data.yaml \
  imgsz=1024 \
  device=0
```

Compare against PyTorch:

```bash
yolo val \
  model=/path/to/best.pt \
  data=/path/to/data.yaml \
  imgsz=1024 \
  device=0
```

Flag differences:

```text
FP16 expected: small numerical differences
INT8 expected: possible mAP drop; must be measured
preprocessing mismatch: can cause large quality drop
```
