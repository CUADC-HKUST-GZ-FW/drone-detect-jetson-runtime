# 04 Cascaded Detection Pipeline

This document describes the two-stage cascade detection design.

## Cascade Definition

The requested cascade is:

```text
full frame
  -> stage1 model: detect location only
  -> select one bbox
  -> crop ROI
  -> stage2 model: determine concrete type/class
```

Stage1 class output is ignored. Stage1 only provides the location box.

Stage2 receives the cropped content and performs the type decision.

## Tested Configurations

Requested:

```text
800x800 + 400x400
1024x1024 + 400x400
```

Actual tested:

```text
800x800 + requested400_actual416
1024x1024 + requested400_actual416
```

Reason:

```text
YOLO max stride = 32
requested 400 is auto-adjusted by Ultralytics to 416
```

## Strict Stage1 Resolution

Stage1 input is strict square:

```text
800 path:  appsink/C++ receives 800x800
1024 path: appsink/C++ receives 1024x1024
```

This is done through:

```text
nvv4l2decoder -> nvvidconv -> nvcompositor -> appsink
```

The compositor creates a square canvas. C++ sets pad rows to YOLO letterbox value `114`.

## Sequential Cascade

Sequential means:

```text
frame N:
  stage1
  crop
  stage2
frame N+1:
  stage1
  crop
  stage2
```

Advantages:

- simpler
- deterministic
- less GPU contention

Disadvantages:

- lower throughput because stage1 and stage2 costs are additive

Measured:

```text
800+416 sequential:  about 97.9 FPS
1024+416 sequential: about 78.3 FPS
```

## Pipeline Parallel Cascade

Pipeline parallel means stage2 for one frame overlaps stage1 for another frame:

```text
time slice 1:
  stage1(frame N)

time slice 2:
  stage1(frame N+1) + stage2(frame N)

time slice 3:
  stage1(frame N+2) + stage2(frame N+1)
```

This is not same-frame parallelism. Stage2 cannot start for the same frame until stage1 has produced the crop box.

Measured:

```text
800+416 pipeline:  about 113.1 FPS
1024+416 pipeline: about 87.5 FPS
```

## Why 1024 Cascade Does Not Reach 90 FPS

Single-model 1024 inference can exceed 90 FPS.

The cascade adds:

- stage1 1024 inference
- bbox parsing
- ROI crop
- stage2 416 preprocessing
- stage2 416 inference
- stage2 type parse

Pipeline parallelism helps, but stage1 and stage2 both use the same GPU. On 1024+416, concurrent TensorRT execution increases stage2 latency. This is the main bottleneck.

## Current Final Result

Best without changing precision or input size:

```text
800 + requested400_actual416:  113.09 FPS
1024 + requested400_actual416: 87.50 FPS
```

## Options To Push 1024 Cascade Above 90

These require product/accuracy approval:

1. Use a lighter stage2 classifier instead of a YOLO detector.
2. Use INT8 for stage2 after calibration and accuracy validation.
3. Run stage2 less frequently and track type between frames.
4. Offload stage2 to DLA if the engine is compatible.
5. Train a dedicated crop classifier at 416 or lower.
6. Reduce stage2 candidate complexity.

Do not silently apply these if the requirement is "do not lower inference quality."

## Stage2 Dataset Recommendation

For high-quality cascade behavior:

- build a crop dataset
- generate crops from stage1 predicted boxes
- include false positives
- include jittered boxes
- include hard negatives
- validate full cascade, not only each stage separately

## C++ Runner Behavior

Current runner:

```text
stage1 output: [1,300,6]
select highest-confidence bbox above threshold
if no bbox: fallback center crop
crop ROI from strict square stage1 frame
letterbox ROI to stage2 actual input
run stage2 TensorRT
parse top stage2 output class
```

Metrics:

- FPS
- active latency
- read time
- stage1 preprocess time
- stage1 inference time
- crop/stage2 preprocess time
- stage2 inference time
- fallback frame count
- average ROI area
- temperature/power/GR3D
