# YOLO26n 800 Wall FPS Optimization Summary

## Setup

- Device: Jetson Orin NX Super, power mode 40W, `jetson_clocks` locked CPU/GPU/EMC.
- Engine: `~/jetson_90fps_yolo26n800/engines/yolo26n_800_fp16.engine`; raw plan: `yolo26n_800_fp16.raw.engine`.
- Input video: `~/jetson_benchmark_assets/videos/benchmark_5min_720p30_coco_val2017_synthetic.mp4`.
- Python paths: 5s warmup, 60s measured. Native C++ paths: 5s warmup, 60s measured per mode.
- Temperature and power were collected with `tegrastats`; native raw tegrastats file covers both raw native modes.

## Results

| Mode | FPS | Frames | Mean ms | P90 ms | GR3D avg/max | GPU temp max | CPU temp max | VDD_IN avg W | Note |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| trtexec_raw_no_transfers_800 | 202.16 |  | 0.00 | 0.00 | 0.0/0 | 0.00 | 0.00 | 0.00 | raw TensorRT via trtexec |
| trtexec_raw_with_transfers_800 | 196.90 |  | 0.00 | 0.00 | 0.0/0 | 0.00 | 0.00 | 0.00 | raw TensorRT via trtexec |
| native_trt_gpu_resident | 176.01 | 10561 | 5.68 | 5.70 | 95.6/97 | 69.28 | 69.16 | 19.78 | native C++ TensorRT runner; tegrastats covers both native modes |
| native_trt_h2d_d2h | 169.79 | 10188 | 5.89 | 5.90 | 95.6/97 | 69.28 | 69.16 | 19.78 | native C++ TensorRT runner; tegrastats covers both native modes |
| native_cpp_gstreamer_preprocess_trt | 99.11 | 5947 | 10.09 | 10.29 | 56.3/66 | 65.38 | 66.44 | 17.32 | native C++ GStreamer hwdecode + CPU letterbox/normalize + TensorRT; read 0.43 ms, preprocess 3.60 ms, infer/copy 6.05 ms |
| synthetic_numpy_800 | 64.76 | 3886 | 15.44 | 15.49 | 39.5/47 | 62.81 | 63.84 | 13.42 | Ultralytics/Python path |
| predecoded_ring_800 | 63.76 | 3826 | 15.68 | 15.75 | 38.8/46 | 62.94 | 64.12 | 13.47 | Ultralytics/Python path |
| gstreamer_hwdecode_800 | 59.89 | 3603 | 16.65 | 16.73 | 37.5/42 | 63.19 | 64.53 | 14.43 | Ultralytics/Python path |
| ultralytics_video_800 | 53.48 | 3209 | 18.70 | 18.85 | 32.3/35 | 60.94 | 62.22 | 12.89 | Ultralytics/Python path |
| opencv_videocapture_800 | 52.55 | 3154 | 19.02 | 19.18 | 32.7/35 | 61.47 | 62.94 | 12.87 | Ultralytics/Python path |

## Findings

- Fastest measured end-to-end video path was `native_cpp_gstreamer_preprocess_trt` at `99.11` FPS. This path uses GStreamer/NVIDIA H.264 decode into C++ OpenCV, CPU letterbox/normalize, then direct TensorRT enqueue, avoiding Ultralytics runtime overhead.
- Highest actual video ingest path through Ultralytics/OpenCV was `gstreamer_hwdecode_800` at `59.89` FPS. Hardware H.264 decode via GStreamer raised 800px wall FPS versus Ultralytics video input, but still stayed below 90 FPS because frames return to Python/CPU through appsink and then enter Ultralytics preprocessing/postprocess.
- Removing decode by using predecoded/synthetic frames only reached `64.76` FPS, so decode is not the dominant remaining bottleneck. The dominant cost is the Ultralytics Python predict path, including preprocessing, result construction, and postprocess handling.
- Native TensorRT C++ runner reached `176.01` FPS. The H2D+D2H mode reached `169.79` FPS, which clears the 90 FPS target for an already-preprocessed tensor stream.
- Raw TensorRT via `trtexec` remains around 197 FPS with transfers, consistent with the native runner.
- Thermal headroom was acceptable in this run: Python/GStreamer path GPU max was `63.19C`; native TensorRT combined run GPU max was `69.28C`, CPU max `69.16C`, VDD_IN avg `19.78W`; native C++ video path GPU max was `65.38C`, CPU max `66.44C`, VDD_IN avg `17.32W`.

## Recommendation

For >90 FPS at 800px, stop using Ultralytics `predict()` as the runtime loop. The tested C++ GStreamer + TensorRT path already clears 90 FPS. The next production hardening step is to replace CPU letterbox/normalize with CUDA/NVMM preprocessing and keep decode/preprocess/inference buffers closer to GPU memory for more headroom and lower CPU load.

## Output Files

- `~/jetson_90fps_yolo26n800/yolo26n800_realtime_probe.md`
- `~/jetson_90fps_yolo26n800/yolo26n800_optimization_summary.md`
- `~/jetson_90fps_yolo26n800/yolo26n800_optimization_summary.csv`
- `~/jetson_90fps_yolo26n800/yolo26n800_optimization_summary.json`
- `~/jetson_90fps_yolo26n800/logs/native_trt_runner.jsonl`
- `~/jetson_90fps_yolo26n800/logs/native_trt_video_runner.json`
- `~/jetson_90fps_yolo26n800/tegrastats/`
