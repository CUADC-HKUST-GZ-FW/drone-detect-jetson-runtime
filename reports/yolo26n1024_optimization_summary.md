# YOLO26n 1024 End-to-End Wall FPS Optimization Report

## Setup

- Device: Jetson Orin NX Super, 40W mode, `jetson_clocks` locked CPU/GPU/EMC.
- Model: `yolo26n.pt`, exported TensorRT FP16 engine from the existing formal benchmark.
- Engine: `~/jetson_90fps_yolo26n1024/engines/yolo26n_1024_fp16.engine`.
- Raw TensorRT plan: `~/jetson_90fps_yolo26n1024/engines/yolo26n_1024_fp16.raw.engine`.
- Engine metadata: `imgsz=[1024, 1024]`, `half=True`, `int8=False`, `end2end=True`.
- Main final input: 1080p30 synthetic COCO-val H.264 MP4; simulated video is used as allowed.
- Quality was not lowered: the final path keeps the same 1024x1024 model input and FP16 TensorRT precision. The GStreamer caps optimization scales the 16:9 source to 1024x576 before the same 1024x1024 letterbox padding.

## Results

| Run | FPS | Frames | Mean ms | P90 ms | Read ms | Pre ms | Infer/copy ms | GR3D avg/max | GPU temp max | CPU temp max | VDD avg W | Note |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| pipeline_1080p_caps1024x576_60s | 116.31 | 6982 | 13.31 | 13.42 | 0.35 | 4.41 | 8.55 | 95.5/97 | 72.34 | 72.62 | 23.16 | 1080p source; nvvidconv scales to 1024x576 before appsink; 60s final |
| pipeline_720p_slots4 | 116.27 | 6980 | 15.14 | 15.49 | 0.48 | 6.10 | 8.55 | 94.1/97 | 71.69 | 72.25 | 23.60 | 720p source; threaded C++ pipeline; 4 pinned slots |
| pipeline_720p_slots2_short | 116.15 | 3486 | 15.13 | 15.51 | 0.46 | 6.11 | 8.55 | 94.1/97 | 70.75 | 71.31 | 23.38 | 720p source; threaded C++ pipeline; 2 pinned slots; 30s |
| pipeline_1080p_caps1024x576_short | 116.03 | 3485 | 13.36 | 13.56 | 0.33 | 4.46 | 8.57 | 94.1/97 | 69.97 | 70.38 | 22.73 | 1080p source; nvvidconv scales to 1024x576 before appsink; 30s |
| pipeline_720p_slots6_short | 115.64 | 3475 | 15.16 | 15.52 | 0.46 | 6.10 | 8.60 | 94.1/97 | 72.28 | 72.84 | 23.56 | 720p source; threaded C++ pipeline; 6 pinned slots; 30s |
| pipeline_1080p_no_caps | 83.59 | 5017 | 20.32 | 20.74 | 5.77 | 6.14 | 8.40 | 66.7/87 | 69.94 | 71.00 | 20.11 | 1080p source; threaded C++ pipeline; full frame to appsink |
| baseline_720p_serial | 69.96 | 4198 | 14.29 | 14.57 | 0.45 | 5.58 | 8.26 | 56.4/65 | 66.97 | 67.84 | 18.02 | 720p source; serial C++ hwdecode/preprocess/TRT |

## Findings

- Final 1024x1024 end-to-end path reached `116.31` FPS for 60 seconds on the 1080p source, processing `6982` frames.
- Baseline serial 720p C++ path was `69.96` FPS. Threading decode/preprocess and TRT with pinned slots raised the 720p path to about `116 FPS`.
- 1080p without GStreamer caps was `83.59` FPS because appsink/read cost rose to `5.77` ms. Adding `nvvidconv` caps `1024x576` reduced read cost to `0.35` ms and restored >90 FPS.
- Slot count was not sensitive after pipelining: 2, 4, and 6 slots all measured about 115-116 FPS; 4 slots is a good default.
- Final thermal/power summary: GPU max `72.34C`, CPU max `72.62C`, VDD_IN avg `23.16W`, GR3D avg/max `95.5/97%`.

## Recommendation

Use the `native_trt_video_pipeline_runner` path for 1024 real-time work: GStreamer H.264 hardware decode, `nvvidconv` resize caps to the letterbox-scaled source dimensions, C++ pinned-slot pipeline, and direct TensorRT FP16 enqueue. The next optimization with meaningful upside would be moving letterbox/normalize from CPU OpenCV to CUDA/NVMM, but the current path already exceeds the 90 FPS target.

## Output Files

- `~/jetson_90fps_yolo26n1024/yolo26n1024_optimization_summary.md`
- `~/jetson_90fps_yolo26n1024/yolo26n1024_optimization_summary.csv`
- `~/jetson_90fps_yolo26n1024/yolo26n1024_optimization_summary.json`
- `~/jetson_90fps_yolo26n1024/scripts/native_trt_video_pipeline_runner`
- `~/jetson_90fps_yolo26n1024/logs/`
- `~/jetson_90fps_yolo26n1024/tegrastats/`
