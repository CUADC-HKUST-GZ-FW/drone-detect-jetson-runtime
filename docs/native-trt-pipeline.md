# Native TensorRT Video Pipeline

This path is the production-oriented YOLO runtime for Jetson AGX. It avoids
Ultralytics `model.predict()` in the frame loop and uses:

- GStreamer `nvv4l2decoder enable-max-performance=1`
- `nvvidconv` scaling before appsink
- C++ preprocessing into preallocated pinned slots
- TensorRT raw engine `enqueueV3`
- Fixed-interval JSON metrics instead of per-frame Python result objects

## Build On Each AGX

```bash
cd /opt/drone-detect
make -C native -j"$(nproc)"
```

## Export Engine On The Target AGX

Do not reuse an engine generated on another Jetson class. Export from the `.pt`
on the target device:

```bash
cd /opt/drone-detect
.venv/bin/python scripts/export_yolo_engine.py --model yolo26n.pt --imgsz 1024 --device 0 --half true --workspace 4
.venv/bin/python scripts/strip_ultralytics_engine.py models/trt/yolo26n_1024_fp16_ultralytics.engine --verify
```

The C++ runner loads the `.raw.engine` file.

## Benchmark

Fast 16:9 path, with hardware decode and `1024x576` caps before C++ padding:

```bash
WARMUP=3 MEASURE=20 TARGET=1024 SLOTS=4 CAPS_W=1024 CAPS_H=576 MODE=pipeline \
  bash scripts/run_native_trt_benchmark.sh models/trt/yolo26n_1024_fp16_ultralytics.raw.engine assets/test_20s.mp4
```

Strict square path, with `nvcompositor` creating a `1024x1024` appsink frame:

```bash
WARMUP=3 MEASURE=20 TARGET=1024 SLOTS=4 CAPS_W=1024 CAPS_H=576 MODE=strict \
  bash scripts/run_native_trt_benchmark.sh models/trt/yolo26n_1024_fp16_ultralytics.raw.engine assets/test_20s.mp4
```

Run `tegrastats --interval 1000` in parallel when collecting final numbers.

See `docs/native-trt-agx-results-2026-06-16.md` for the AGX validation run.
