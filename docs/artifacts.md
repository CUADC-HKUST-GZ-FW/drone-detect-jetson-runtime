# Model And Data Artifacts

This repository intentionally does not track model weights, TensorRT engines,
videos, datasets, or generated benchmark outputs.

## Expected Local Paths

```text
yolo26n.pt
models/trt/yolo26n_1024_fp16_ultralytics.engine
models/trt/yolo26n_1024_fp16_ultralytics.raw.engine
assets/test_20s.mp4
results/
```

All of those paths are ignored by Git.

## Why Engines Are Not Portable

TensorRT engine files are tied to the target device class, TensorRT version,
CUDA version, plugins, and sometimes builder flags. Build engines on the
machine that will run inference, or on an identical deployment image.

Use:

```bash
python3 scripts/export_yolo_engine.py --model yolo26n.pt --imgsz 1024 --device 0 --half true --workspace 4
python3 scripts/strip_ultralytics_engine.py models/trt/yolo26n_1024_fp16_ultralytics.engine --verify
```

The native C++ runners load the `.raw.engine` output.

## Suggested Distribution

- Put small source code, docs, configs, and tests in Git.
- Publish sample videos and public benchmark logs as GitHub Release assets if needed.
- Use Git LFS or object storage for private model weights and datasets.
- Document checksums for released artifacts.

Example checksum manifest:

```text
sha256  filename
...     yolo26n.pt
...     yolo26n_1024_fp16_ultralytics.raw.engine
...     test_20s.mp4
```
