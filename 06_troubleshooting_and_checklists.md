# 06 Troubleshooting And Checklists

## Training Checklist

- [ ] Dataset has stable class ids.
- [ ] `data.yaml` paths are absolute or correct relative paths.
- [ ] Train/val/test split is scene-separated for video datasets.
- [ ] Labels are normalized YOLO boxes.
- [ ] Stage2 crop dataset matches deployment crop distribution.
- [ ] Validation set includes hard negatives.
- [ ] Class imbalance is measured.
- [ ] Target deployment resolution is included in validation.

## Export Checklist

- [ ] Export performed on Jetson or matching TensorRT/CUDA stack.
- [ ] Actual engine size recorded.
- [ ] Precision recorded.
- [ ] Ultralytics metadata saved.
- [ ] Raw TensorRT plan generated for C++.
- [ ] `trtexec` smoke test passed.
- [ ] TensorRT validation compared against PyTorch if accuracy matters.

## C++ Deployment Checklist

- [ ] Uses raw TensorRT plan.
- [ ] Reuses TensorRT context.
- [ ] Uses preallocated GPU buffers.
- [ ] Uses pinned host memory.
- [ ] Avoids per-frame allocation.
- [ ] Avoids per-frame logging.
- [ ] Avoids drawing/saving/showing frames during benchmark.
- [ ] Uses GStreamer NVIDIA decoder.
- [ ] Uses `nvvidconv` for conversion/scaling.
- [ ] Uses `nvcompositor` when strict square canvas is required.
- [ ] Records tegrastats.

## Resolution Checklist

For strict `1024x1024`:

- [ ] Engine metadata says `imgsz=[1024,1024]`.
- [ ] appsink/C++ frame is `1024x1024`.
- [ ] C++ checks frame dimensions.
- [ ] Padding color is YOLO letterbox `114`, not accidental black.
- [ ] No 16:9 stretch is used unless explicitly accepted.

For stage2 requested `400`:

- [ ] Export log checked for stride adjustment.
- [ ] Actual engine metadata checked.
- [ ] Report says `requested400_actual416` if actual is 416.

## GStreamer Troubleshooting

Check plugins:

```bash
gst-inspect-1.0 nvv4l2decoder
gst-inspect-1.0 nvvidconv
gst-inspect-1.0 nvcompositor
```

Smoke test decode:

```bash
gst-launch-1.0 -q \
  filesrc location=video.mp4 \
  ! qtdemux ! h264parse \
  ! nvv4l2decoder enable-max-performance=1 \
  ! fakesink sync=false
```

If OpenCV GStreamer cannot open:

- check quoting of `video/x-raw(memory:NVMM)`
- remove caps and test simpler pipeline
- test with `gst-launch-1.0`
- confirm OpenCV was built with GStreamer support

## TensorRT Troubleshooting

If `trtexec` fails on Ultralytics engine:

- strip metadata prefix
- use `.raw.engine`

If engine input size differs:

- inspect metadata
- inspect export log
- check stride multiple

If FPS is much lower than raw TensorRT:

- decode path may be slow
- appsink may copy full-resolution frames
- Python may be in the loop
- preprocessing may allocate every frame
- output postprocessing may be excessive

## Thermal/Power Troubleshooting

If FPS drops over time:

- check GPU temp
- check CPU temp
- check GR3D clock
- check EMC clock
- check fan speed
- check power mode

Commands:

```bash
tegrastats
sudo jetson_clocks --show
sudo nvpmodel -q --verbose
```

## Cascade Troubleshooting

If fallback count is high:

- stage1 threshold may be too high
- stage1 model may not detect target class
- input preprocessing may mismatch training
- video content may not include expected objects

If 1024 cascade is below 90 FPS:

- stage1 and stage2 compete for GPU
- stage2 detector may be too heavy for every-frame cascade
- use a lighter stage2 classifier if acceptable
- consider stage2 INT8 only after accuracy validation
- consider tracking/type reuse across frames

If stage2 quality is poor:

- train stage2 on crops, not full images
- include stage1 predicted crop noise
- use jittered boxes
- include negative crops

## Reporting Checklist

- [ ] Report exact command or script.
- [ ] Report exact paths.
- [ ] Report engine metadata.
- [ ] Report requested vs actual input sizes.
- [ ] Report precision.
- [ ] Report strict resolution policy.
- [ ] Report FPS and latency.
- [ ] Report tegrastats summary.
- [ ] Report known limitations.
- [ ] Report what would be required for further speedup.
