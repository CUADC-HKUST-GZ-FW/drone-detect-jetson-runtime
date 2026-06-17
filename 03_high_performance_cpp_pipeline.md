# 03 High Performance C++ Pipeline

This document describes the high-performance Jetson deployment pipeline used in the benchmark work.

## Why Not Ultralytics `predict()` For Production

Ultralytics `predict()` is excellent for development and validation, but it adds Python overhead:

- video decode handoff
- preprocessing
- result object creation
- postprocessing abstraction
- per-frame Python dispatch

On the tested Jetson, raw TensorRT was much faster than Ultralytics wall FPS. Production throughput required C++ TensorRT.

## Target Runtime Architecture

Recommended single-model path:

```text
H.264/H.265 video
  -> GStreamer filesrc/camerasrc
  -> nvv4l2decoder
  -> nvvidconv
  -> nvcompositor if strict square canvas is required
  -> appsink BGR
  -> C++ pinned-slot pipeline
  -> letterbox/normalize
  -> TensorRT FP16 enqueue
  -> output parse
```

For strict square input:

```text
16:9 source -> scaled content -> 1024x1024 NVMM compositor canvas -> appsink 1024x1024 BGR
```

This keeps the C++ input frame and model input as `1024x1024`.

## GStreamer Building Blocks

Hardware decode:

```text
nvv4l2decoder enable-max-performance=1
```

NVIDIA conversion/scaling:

```text
nvvidconv
```

NVIDIA compositor:

```text
nvcompositor background=black sink_0::xpos=0 sink_0::ypos=<pad_y> sink_0::width=<w> sink_0::height=<h>
```

OpenCV appsink:

```text
appsink drop=true sync=false max-buffers=4
```

## Strict `1024x1024` Pipeline

For a 16:9 1080p source and `1024x1024` model input:

```text
filesrc location=video.mp4
  ! qtdemux
  ! h264parse
  ! nvv4l2decoder enable-max-performance=1
  ! nvvidconv
  ! video/x-raw(memory:NVMM),format=RGBA,width=1024,height=576
  ! nvcompositor name=comp background=black
      sink_0::xpos=0 sink_0::ypos=212
      sink_0::width=1024 sink_0::height=576
  ! video/x-raw(memory:NVMM),format=RGBA,width=1024,height=1024
  ! nvvidconv
  ! video/x-raw,format=BGRx
  ! videoconvert
  ! video/x-raw,format=BGR
  ! appsink drop=true sync=false max-buffers=4
```

The C++ preprocessing then sets padding rows to YOLO letterbox value `114`, converts BGR to RGB, normalizes to `[0,1]`, and writes NCHW float input.

## Pinned Slots

Use preallocated pinned host memory for input tensors:

```text
cudaHostAlloc(stage_input_host)
cudaMalloc(stage_input_device)
cudaMemcpyAsync(H2D)
context->enqueueV3(stream)
cudaMemcpyAsync(D2H)
```

Use multiple slots so video read/preprocess can overlap TensorRT inference:

```text
producer thread -> ready queue -> inference thread
```

Recommended default:

```text
slots=4
```

Tests showed 2, 4, and 6 slots were close after pipelining; 4 is a good default.

## TensorRT C++ Runtime

Use raw TensorRT plan without Ultralytics metadata prefix.

Core flow:

```cpp
runtime = nvinfer1::createInferRuntime(logger);
engine = runtime->deserializeCudaEngine(bytes.data(), bytes.size());
context = engine->createExecutionContext();
context->setTensorAddress(input_name, input_dev);
context->setTensorAddress(output_name, output_dev);
context->enqueueV3(stream);
```

## Current Measured Single-Model Results

Strict `1024x1024` single-model C++ path:

```text
FPS: about 103
input: 1080p synthetic H.264
appsink/C++ frame: 1024x1024
engine: yolo26n 1024 FP16
```

Previous non-strict content-scaled path:

```text
FPS: about 116
appsink frame: 1024x576
C++ padded to 1024x1024
```

Use the strict path when the requirement says the pipeline must keep `1024x1024` resolution.

## Optimization Levers

Safe levers:

- C++ TensorRT instead of Python Ultralytics loop
- pinned host memory
- fixed input shapes
- multiple buffering
- GStreamer hardware decode
- NVMM scaling/compositing before appsink
- avoid per-frame logging
- avoid drawing/saving/showing frames
- reuse contexts and buffers

Quality-changing levers:

- lower input resolution
- INT8 without validation
- frame skipping
- distorted resize instead of letterbox
- using stage1 class instead of stage2

Quality-changing levers must be explicitly approved and measured.

## Monitoring

Use tegrastats:

```bash
tegrastats --interval 1000 --logfile tegrastats/run.log
```

Track:

- GR3D_FREQ
- RAM
- CPU frequencies/utilization
- GPU temperature
- CPU temperature
- VDD_IN

## Current C++ Script Paths

```bash
~/jetson_90fps_yolo26n1024/scripts/native_trt_video_strict_square_runner
~/jetson_90fps_yolo26n1024/scripts/native_trt_video_pipeline_runner
~/jetson_cascade_benchmark/scripts/cascade_trt_runner
~/jetson_cascade_benchmark/scripts/cascade_trt_pipeline_runner
```
