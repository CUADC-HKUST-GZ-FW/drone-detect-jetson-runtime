# Native TensorRT Runners

This directory contains the C++ TensorRT/GStreamer benchmark runners copied from the Jetson Orin NX optimization work.

The runners are source-only in this repository. Build outputs, TensorRT engines, model weights, videos, and raw logs are intentionally excluded from git.

## Build On Jetson

Tested target stack:

- NVIDIA Jetson Orin NX
- Jetson Linux R36.5
- CUDA from JetPack
- TensorRT 10.3
- OpenCV with GStreamer support

Build all runners:

```bash
make -C native
```

If TensorRT or CUDA are installed in a non-standard location:

```bash
make -C native CUDA_HOME=/usr/local/cuda TRT_INC=/usr/include/aarch64-linux-gnu TRT_LIB=/usr/lib/aarch64-linux-gnu
```

## Runner Examples

Single-model strict square 1024 path:

```bash
native/build/native_trt_video_strict_square_runner_1024 \
  /opt/yolo-pipeline/current/engines/yolo26n_1024_fp16.raw.engine \
  /data/videos/benchmark.mp4 \
  5 60 1024 4 1024 576
```

Single-model 1024 pipeline path:

```bash
native/build/native_trt_video_pipeline_runner_1024 \
  /opt/yolo-pipeline/current/engines/yolo26n_1024_fp16.raw.engine \
  /data/videos/benchmark.mp4 \
  5 60 1024 4 1024 576
```

Cascaded pipeline path:

```bash
native/build/cascade_trt_pipeline_runner \
  /opt/yolo-pipeline/current/engines/yolo26n_800_fp16.raw.engine \
  /opt/yolo-pipeline/current/engines/yolo26n_requested400_actual416_fp16.raw.engine \
  /data/videos/benchmark.mp4 \
  800 416 5 60 4 4
```

The `requested400_actual416` naming is intentional: the YOLO export request is 400, but the resulting model input is 416 because the model stride is 32.
