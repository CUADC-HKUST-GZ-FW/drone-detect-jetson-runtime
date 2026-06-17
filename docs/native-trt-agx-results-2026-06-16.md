# Native TensorRT AGX Results - 2026-06-16

## Environment

- Jetson A: `192.0.2.10`, `jetson_01`
- Jetson B: `192.0.2.20`, `jetson_02`
- Jetson Linux: R36.4.7
- CUDA toolkit: 12.6
- TensorRT: 10.3.0
- Model: `yolo26n.pt`
- Engine: target-device FP16 TensorRT, exported at `imgsz=1024`
- Raw engine: Ultralytics metadata stripped and TensorRT deserialization verified
- Power state during benchmark: `MODE_30W + jetson_clocks`

`MAXN` and `MODE_50W` are available in `/etc/nvpmodel.conf`, but both require
a reboot from the current mode. They were not applied during this run.

## Implemented Optimizations

- Native C++ TensorRT `enqueueV3` runner
- Target-device TensorRT engine export
- Ultralytics engine metadata stripping for raw plan loading
- GStreamer NVIDIA hardware decode through `nvv4l2decoder`
- `nvvidconv` scaling to `1024x576`
- Strict square path through `nvcompositor`
- Preallocated CUDA buffers and pinned host slots
- 4-slot producer/inference pipeline
- JSON metrics output without per-frame drawing or image writes
- `jetson_clocks` applied through the existing privileged runner container

## Benchmark Results

Input video: `assets/test_20s.mp4`, 1280x720, 30 FPS, 600 frames.

| Node | Mode | FPS | Mean read ms | Mean preprocess ms | Mean infer/copy ms |
|---|---:|---:|---:|---:|---:|
| `jetson_01` | C++ pipeline, `1024x576 -> 1024` | 78.19 | 0.90 | 3.83 | 12.19 |
| `jetson_01` | strict `1024x1024` | 79.52 | 0.89 | 3.33 | 12.18 |
| `jetson_02` | C++ pipeline, `1024x576 -> 1024` | 78.20 | 0.91 | 3.81 | 12.19 |
| `jetson_02` | strict `1024x1024` | 79.50 | 0.87 | 3.31 | 12.18 |

Raw TensorRT upper bound with `trtexec --noDataTransfers --useCudaGraph`:

| Node | Raw TensorRT throughput | GPU compute mean |
|---|---:|---:|
| `jetson_01` | 95.94 qps | 10.42 ms |
| `jetson_02` | 96.35 qps | 10.38 ms |

Earlier Python/Ultralytics full-video path at `imgsz=640`:

| Node | End-to-end FPS | Avg inference ms |
|---|---:|---:|
| `jetson_01` | 16.63 | 25.97 |
| `jetson_02` | 13.66 | 26.94 |

The native path is therefore already much faster end-to-end while using a
larger `1024` TensorRT input.

## Remaining Higher-Risk / Deferred Items

- Switching to `MODE_50W` or `MAXN` requires reboot confirmation.
- INT8 was not attempted because it needs calibration and accuracy validation.
- Full C++ detection result formatting is not yet wired into the WebUI; the
current benchmark path measures production inference throughput and emits JSON
metrics.
