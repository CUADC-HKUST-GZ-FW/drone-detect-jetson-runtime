# Jetson Wall FPS Optimization Report

## Scope

- Goal: increase video wall FPS for the fastest 640 TensorRT candidates without rerunning the full 48-combo matrix.
- DeepStream was not installed. DLA/NVDLA was not used as the main execution path.
- Video: `/home/jetson/jetson_benchmark_assets/videos/benchmark_5min_720p30_coco_val2017_synthetic.mp4` (`synthetic_stream_from_coco_val2017`, not a real camera stream).
- All Ultralytics runs used TensorRT engines with `save=False`, `show=False`, `verbose=False`, `stream=True` where applicable, and did not access boxes/results per frame.

## Environment

```text
generated_at: 2026-06-01T04:20:13+00:00
gst_decoder: ok
jetson_clocks: sudo: a password is required
l4t: # R36 (release), REVISION: 5.0, GCID: 43688277, BOARD: generic, EABI: aarch64, DATE: Fri Jan 16 03:50:45 UTC 2026
# KERNEL_VARIANT: oot
TARGET_USERSPACE_LIB_DIR=nvidia
TARGET_USERSPACE_LIB_DIR_PATH=usr/lib/aarch64-linux-gnu/nvidia
nvpmodel_before: NVPM VERB: Config file: /etc/nvpmodel.conf
NVPM VERB: parsing done for /etc/nvpmodel.conf
NVPM VERB: Current mode: NV Power Mode: 40W
4
NVPM VERB: PARAM CPU_ONLINE: ARG CORE_0: PATH /sys/devices/system/cpu/cpu0/online: REAL_VAL: 1 CONF_VAL: 1
NVPM VERB: PARAM CPU_ONLINE: ARG CORE_1: PATH /sys/devices/system/cpu/cpu1/online: REAL_VAL: 1 CONF_VAL: 1
NVPM VERB: PARAM CPU_ONLINE: ARG CORE_2: PATH /sys/devices/system/cpu/cpu2/online: REAL_VAL: 1 CONF_VAL: 1
NVPM VERB: PARAM CPU_ONLINE: ARG CORE_3: PATH /sys/devices/system/cpu/cpu3/online: REAL_VAL: 1 CONF_VAL: 1
NVPM VERB: PARAM CPU_ONLINE: ARG CORE_4: PATH /sys/devices/system/cpu/cpu4/online: REAL_VAL: 1 CONF_VAL: 1
NVPM VERB: PARAM CPU_ONLINE: ARG CORE_5: PATH /sys/devices/system/cpu/cpu5/online: REAL_VAL: 1 CONF_VAL: 1
NVPM VERB: PARAM CPU_ONLINE: ARG CORE_6: PATH /sys/devices/system/cpu/cpu6/online: REAL_VAL: 1 CONF_VAL: 1
NVPM VERB: PARAM CPU_ONLINE: ARG CORE_7: PATH /sys/devices/system/cpu/cpu7/online: REAL_VAL: 1 CONF_VAL: 1
NVPM VERB: PARAM FBP_POWER_GATING: ARG FBP_PG_MASK: PATH /sys/devices/platform/gpu.0/fbp_pg_mask: REAL_VAL: 2 CONF_VAL: 2
NVPM VERB: PARAM TPC_POWER_GATING: ARG TPC_PG_MASK: PATH /sys/devices/platform/gpu.0/tpc_pg_mask: REAL_VAL: 240 CONF_VAL: 240
NVPM VERB: PARAM GPU_POWER_CONTROL_ENABLE: ARG GPU_PWR_CNTL_EN: PATH /sys/devices/platform/gpu.0/power/control: REAL_VAL: auto CONF_VAL: on
NVPM VERB: PARAM CPU_A78_0: ARG MIN_FREQ: PATH /sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq: REAL_VAL: 729600 CONF_VAL: 729600
NVPM VERB: PARAM CPU_A78_0: ARG MAX_FREQ: PATH /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq: REAL_VAL: 1497600 CONF_VAL: 1497600
NVPM VERB: PARAM CPU_A78_1: ARG MIN_FREQ: PATH /sys/devices/system/cpu/cpu1/cpufreq/scaling_min_freq: REAL_VAL: 729600 CONF_VAL: 729600
NVPM VERB: PARAM CPU_A78_1: ARG MAX_FREQ: PATH /sys/devices/system/cpu/cpu1/cpufreq/scaling_max_freq: REAL_VAL: 1497600 CONF_VAL: 1497600
NVPM VERB: PARAM CPU_A78_2: ARG MIN_FREQ: PATH /sys/devices/system/cpu/cpu2/cpufreq/scaling_min_freq: REAL_VAL: 729600 CONF_VAL: 729600
NVPM VERB: PARAM CPU_A78_2: ARG MAX_FREQ: PATH /sys/devices/system/cpu/cpu2/cpufreq/scaling_max_freq: REAL_VAL: 1497600 CONF_VAL: 1497600
NVPM VERB: PARAM CPU_A78_3: ARG MIN_FREQ: PATH /sys/devices/system/cpu/cpu3/cpufreq/scaling_min_freq: REAL_VAL: 729600 CONF_VAL: 729600
NVPM VERB: PARAM CPU_A78_3: ARG MAX_FREQ: PATH /sys/devices/system/cpu/cpu3/cpufreq/scaling_max_freq: REAL_VAL: 1497600 CONF_VAL: 1497600
NVPM VERB: PARAM CPU_A78_4: ARG MIN_FREQ: PATH /sys/devices/system/cpu/cpu4/cpufreq/scaling_min_freq: REAL_VAL: 729600 CONF_VAL: 729600
NVPM VERB: PARAM CPU_A78_4: ARG MAX_FREQ: PATH /sys/devices/system/cpu/cpu4/cpufreq/scaling_max_freq: REAL_VAL: 1497600 CONF_VAL: 1497600
NVPM VERB: PARAM CPU_A78_5: ARG MIN_FREQ: PATH /sys/devices/system/cpu/cpu5/cpufreq/scaling_min_freq: REAL_VAL: 729600 CONF_VAL: 729600
NVPM VERB: PARAM CPU_A78_5: ARG MAX_FREQ: PATH /sys/devices/system/cpu/cpu5/cpufreq/scaling_max_freq: REAL_VAL: 1497600 CONF_VAL: 1497600
NVPM VERB: PARAM CPU_A78_6: ARG MIN_FREQ: PATH /sys/devices/system/cpu/cpu6/cpufreq/scaling_min_freq: REAL_VAL: 729600 CONF_VAL: 729600
NVPM VERB: PARAM CPU_A78_6: ARG MAX_FREQ: PATH /sys/devices/system/cpu/cpu6/cpufreq/scaling_max_freq: REAL_VAL: 1497600 CONF_VAL: 1497600
NVPM VERB: PARAM CPU_A78_7: ARG MIN_FREQ: PATH /sys/devices/system/cpu/cpu7/cpufreq/scaling_min_freq: REAL_VAL: 729600 CONF_VAL: 729600
NVPM VERB: PARAM CPU_A78_7: ARG MAX_FREQ: PATH /sys/devices/system/cpu/cpu7/cpufreq/scaling_max_freq: REAL_VAL: 1497600 CONF_VAL: 1497600
NVPM VERB: PARAM GPU: ARG MIN_FREQ: PATH /sys/devices/platform/17000000.gpu/devfreq_dev/min_freq: REAL_VAL: 306000000 CONF_VAL: 0
NVPM VERB: PARAM GPU: ARG MAX_FREQ: PATH /sys/devices/platform/17000000.gpu/devfreq_dev/max_freq: REAL_VAL: 1173000000 CONF_VAL: 1173000000
NVPM VERB: PARAM GPU_POWER_CONTROL_DISABLE: ARG GPU_PWR_CNTL_DIS: PATH /sys/devices/platform/gpu.0/power/control: REAL_VAL: auto CONF_VAL: auto
NVPM VERB: PARAM EMC: ARG MAX_FREQ: PATH /sys/kernel/nvpmodel_clk_cap/emc: REAL_VAL: 3199000000 CONF_VAL: 9223372036854775807
NVPM VERB: PARAM DLA0_CORE: ARG MAX_FREQ: PATH /sys/devices/platform/bus@0/13e00000.host1x/15880000.nvdla0/clk_cap/dla0_core: REAL_VAL: 908800000 CONF_VAL: 908800000
NVPM VERB: PARAM DLA1_CORE: ARG MAX_FREQ: PATH /sys/devices/platform/bus@0/13e00000.host1x/158c0000.nvdla1/clk_cap/dla1_core: REAL_VAL: 908800000 CONF_VAL: 908800000
NVPM VERB: PARAM DLA0_FALCON: ARG MAX_FREQ: PATH /sys/devices/platform/bus@0/13e00000.host1x/15880000.nvdla0/clk_cap/dla0_falcon: REAL_VAL: 435200000 CONF_VAL: 435200000
NVPM VERB: PARAM DLA1_FALCON: ARG MAX_FREQ: PATH /sys/devices/platform/bus@0/13e00000.host1x/158c0000.nvdla1/clk_cap/dla1_falcon: REAL_VAL: 435200000 CONF_VAL: 435200000
NVPM VERB: PARAM PVA0_VPS: ARG MAX_FREQ: PATH /sys/devices/platform/bus@0/13e00000.host1x/16000000.pva0/clk_cap/pva0_vps: REAL_VAL: 704000000 CONF_VAL: 704000000
NVPM VERB: PARAM PVA0_AXI: ARG MAX_FREQ: PATH /sys/devices/platform/bus@0/13e00000.host1x/16000000.pva0/clk_cap/pva0_cpu_axi: REAL_VAL: 486400000 CONF_VAL: 486400000
opencv_gstreamer:     GStreamer:                   YES (1.20.3)
video_info: {"duration_sec": 299.73333333333335, "fps": 30.0, "frames": 8992, "height": 720, "opened": true, "path": "/home/jetson/jetson_benchmark_assets/videos/benchmark_5min_720p30_coco_val2017_synthetic.mp4", "width": 1280}
```

## Conclusion

- Highest measured video/Python wall FPS: `synthetic_numpy_frame_loop` on `yolo11n.pt` `int8` at `50.77` FPS.
- Gain over Ultralytics video baseline for the same engine: `28.29`%.
- `predecoded_frame_ring` and `synthetic_numpy_frame_loop` estimate Python+Ultralytics+TensorRT upper bounds after removing decode/file IO. They are not end-to-end camera/video FPS.
- GStreamer appsink uses Jetson hardware H.264 decode, but still copies frames into Python/CPU memory; this is not DeepStream zero-copy.

## Results

| Model | Precision | Input mode | Frames | Wall FPS | Mean wall ms | Mean read ms | Mean predict ms | GR3D avg/max | GPU temp max C | VDD_IN avg/max mW | Notes |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| yolo11n.pt | int8 | synthetic_numpy_frame_loop | 6093 | 50.77 | 19.69 |  | 19.69 | 57.66/67 | 54.50 | 6941/7544 | minimal_result_handling; save/show/verbose disabled; boxes not accessed; synthetic_numpy_frame; no decode and no real image diversity |
| yolo26n.pt | int8 | synthetic_numpy_frame_loop | 5983 | 49.85 | 20.05 |  | 20.05 | 56.59/71 | 53.91 | 6863/7062 | minimal_result_handling; save/show/verbose disabled; boxes not accessed; synthetic_numpy_frame; no decode and no real image diversity |
| yolo26n.pt | fp16 | synthetic_numpy_frame_loop | 5769 | 48.07 | 20.79 |  | 20.79 | 64.97/77 | 54.78 | 7293/7544 | minimal_result_handling; save/show/verbose disabled; boxes not accessed; synthetic_numpy_frame; no decode and no real image diversity |
| yolo26n.pt | fp16 | predecoded_frame_ring | 5643 | 47.02 | 21.26 |  | 21.26 | 62.24/77 | 55.12 | 7288/7624 | minimal_result_handling; save/show/verbose disabled; boxes not accessed; predecoded_ring_frames=300; decode excluded from measurement |
| yolo26n.pt | fp16 | gstreamer_hwdecode_appsink | 5597 | 46.57 | 21.43 | 0.71 | 20.72 | 63.33/78 | 55.94 | 8388/8747 | minimal_result_handling; save/show/verbose disabled; boxes not accessed; nvv4l2decoder+nvvidconv+appsink; not DeepStream zero-copy |
| yolo11n.pt | int8 | gstreamer_hwdecode_appsink | 5496 | 45.73 | 21.83 | 0.70 | 21.12 | 53.71/67 | 55.19 | 7981/8186 | minimal_result_handling; save/show/verbose disabled; boxes not accessed; nvv4l2decoder+nvvidconv+appsink; not DeepStream zero-copy |
| yolo26n.pt | int8 | gstreamer_hwdecode_appsink | 5481 | 45.60 | 21.89 | 0.70 | 21.19 | 54.65/70 | 54.94 | 7930/8186 | minimal_result_handling; save/show/verbose disabled; boxes not accessed; nvv4l2decoder+nvvidconv+appsink; not DeepStream zero-copy |
| yolo11n.pt | int8 | predecoded_frame_ring | 5382 | 44.85 | 22.29 |  | 22.29 | 52.42/67 | 54.56 | 6863/7503 | minimal_result_handling; save/show/verbose disabled; boxes not accessed; predecoded_ring_frames=300; decode excluded from measurement |
| yolo26n.pt | int8 | predecoded_frame_ring | 5283 | 44.02 | 22.71 |  | 22.71 | 54.40/68 | 54.22 | 6796/6902 | minimal_result_handling; save/show/verbose disabled; boxes not accessed; predecoded_ring_frames=300; decode excluded from measurement |
| yolo11n.pt | int8 | baseline_ultralytics_video | 4750 | 39.58 | 25.27 |  | 10.24 | 47.37/67 | 54.50 | 6930/7383 | minimal_result_handling; save/show/verbose disabled; boxes not accessed |
| yolo11n.pt | int8 | opencv_video_capture | 4712 | 39.26 | 25.46 | 4.46 | 21.00 | 47.35/68 | 54.25 | 6916/7062 | minimal_result_handling; save/show/verbose disabled; boxes not accessed |
| yolo26n.pt | fp16 | baseline_ultralytics_video | 4711 | 39.26 | 25.47 |  | 12.50 | 52.18/77 | 54.75 | 7258/8186 | minimal_result_handling; save/show/verbose disabled; boxes not accessed |
| yolo26n.pt | int8 | baseline_ultralytics_video | 4711 | 39.25 | 25.48 |  | 10.63 | 47.70/70 | 54.03 | 6872/7022 | minimal_result_handling; save/show/verbose disabled; boxes not accessed |
| yolo26n.pt | int8 | opencv_video_capture | 4648 | 38.73 | 25.81 | 4.45 | 21.36 | 45.47/69 | 53.88 | 6859/7102 | minimal_result_handling; save/show/verbose disabled; boxes not accessed |
| yolo26n.pt | fp16 | opencv_video_capture | 4639 | 38.65 | 25.86 | 4.97 | 20.89 | 52.24/77 | 54.75 | 7197/7463 | minimal_result_handling; save/show/verbose disabled; boxes not accessed |
| yolo26n.pt | int8 | trtexec_raw_no_data_transfers |  |  |  |  |  | 0.00/0 | 52.78 | 6133/6310 | trtexec failed before measurement: LLVM ERROR: out of memory while loading TensorRT standard plugins; raw TensorRT probe unavailable; not vi |
| yolo11n.pt | int8 | trtexec_raw_no_data_transfers |  |  |  |  |  | 0.00/0 | 53.03 | 5707/5707 | trtexec failed before measurement: LLVM ERROR: out of memory while loading TensorRT standard plugins; raw TensorRT probe unavailable; not vi |
| yolo26n.pt | fp16 | trtexec_raw_no_data_transfers |  |  |  |  |  | 0.00/0 | 52.97 | 5626/5626 | trtexec failed before measurement: LLVM ERROR: out of memory while loading TensorRT standard plugins; raw TensorRT probe unavailable; not vi |

## Interpretation

- `synthetic_numpy_frame_loop` average across tested engines: `49.56` FPS.
- `gstreamer_hwdecode_appsink` average across tested engines: `45.97` FPS.
- `predecoded_frame_ring` average across tested engines: `45.30` FPS.
- `baseline_ultralytics_video` average across tested engines: `39.36` FPS.
- `opencv_video_capture` average across tested engines: `38.88` FPS.
- `trtexec_raw_no_data_transfers` is a pure TensorRT reference and should not be compared directly with video wall FPS.
- Recommended deployment path: keep TensorRT engines, use a hardware-decoded pipeline, and move preprocessing/postprocessing out of Python when possible. For true zero-copy video analytics, a DeepStream or custom GStreamer/CUDA path would be the next step, but DeepStream was intentionally not installed in this run.

## Output Files

- CSV: `/home/jetson/jetson_wallfps_optimization/wallfps_results.csv`
- JSON: `/home/jetson/jetson_wallfps_optimization/wallfps_results.json`
- JSONL: `/home/jetson/jetson_wallfps_optimization/wallfps_results.jsonl`
- logs: `/home/jetson/jetson_wallfps_optimization/logs`
- tegrastats: `/home/jetson/jetson_wallfps_optimization/tegrastats`

## Final Summary

- Best actual video-ingest path: `yolo26n.pt` `fp16` via `gstreamer_hwdecode_appsink` at `46.57` FPS.
- Best INT8 actual video-ingest path: `yolo11n.pt` via `gstreamer_hwdecode_appsink` at `45.73` FPS.
- Best decode-free predecoded-frame estimate: `yolo26n.pt` `fp16` at `47.02` FPS.
- Best synthetic no-decode upper-bound estimate: `yolo11n.pt` `int8` at `50.77` FPS.

### GStreamer Hardware Decode Gain

- `yolo11n.pt` `int8`: GStreamer `45.73` FPS vs baseline `39.58` FPS = `+15.6%`; OpenCV baseline `39.26` FPS.
- `yolo26n.pt` `fp16`: GStreamer `46.57` FPS vs baseline `39.26` FPS = `+18.6%`; OpenCV baseline `38.65` FPS.
- `yolo26n.pt` `int8`: GStreamer `45.60` FPS vs baseline `39.25` FPS = `+16.2%`; OpenCV baseline `38.73` FPS.

### Bottleneck Assessment

- Hardware H.264 decode through `nvv4l2decoder + nvvidconv + appsink` is the best real video path tested, improving wall FPS by roughly 16-19% over direct Ultralytics video reading.
- Plain OpenCV `VideoCapture` does not improve wall FPS; read time is about 4.4-5.0 ms/frame, which cancels out any benefit.
- Predecoded and synthetic loops show the Python + Ultralytics + TensorRT + postprocess ceiling is around 45-51 FPS for these 640 engines. After decode is improved, the next bottleneck is Python/Ultralytics per-frame preprocessing/postprocessing/result-object overhead rather than TensorRT engine execution alone.
- Recommended next deployment path: keep TensorRT engines, use Jetson hardware decode, and move frame conversion, preprocess, and postprocess into a native GStreamer/CUDA or DeepStream-style zero-copy pipeline. DeepStream was intentionally not installed in this run.
