# Cascaded YOLO C++ TensorRT Benchmark Report

## Setup

- Device: Jetson Orin NX Super, 40W mode, `jetson_clocks` locked.
- Video: `~/jetson_benchmark_assets/videos/benchmark_5min_1080p30_coco_val2017_synthetic.mp4`.
- Stage1 role: location only. The C++ runner ignores stage1 class and uses only the highest-confidence bbox as ROI.
- Stage2 role: type decision. The C++ pipeline runner runs stage2 TensorRT and parses the top output class; type parsing is included in active latency.
- Stage1 input is strict square via NVIDIA GStreamer pipeline and `nvcompositor`, with appsink/C++ receiving full square frames.
- Precision: FP16 TensorRT for all engines; no INT8 used in these final runs.

## Engine Sizes

- Stage1 800 engine metadata: `imgsz=[800, 800]`, `half=True`, `int8=False`.
- Stage1 1024 engine metadata: `imgsz=[1024, 1024]`, `half=True`, `int8=False`.
- Stage2 requested 400, actual engine metadata: `imgsz=[416, 416]`, `half=True`, `int8=False`.
- Note: Ultralytics changed `imgsz=400` to `416` because YOLO max stride is 32. This is recorded as `stage2_requested_size=400`, `stage2_actual_size=416`.

## Results

| Run | FPS | Frames | Active mean ms | Active p90 ms | Read | S1 pre | S1 infer | ROI+S2 pre | S2 infer | Fallbacks | GR3D avg/max | GPU max | CPU max | VDD avg W |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 800+416 sequential | 97.90 | 5878 | 13.03 | 13.50 | 0.35 | 2.51 | 6.14 | 1.42 | 2.61 | 194 | 79.3/89 | 67.06 | 67.75 | 18.65 |
| 1024+416 sequential | 78.29 | 4702 | 17.47 | 18.04 | 0.52 | 4.22 | 8.59 | 1.48 | 2.65 | 236 | 81.8/90 | 69.81 | 70.44 | 20.41 |
| 800+416 pipeline_parse | 113.09 | 6790 | 18.79 | 22.69 | 1.20 | 2.58 | 7.39 | 1.39 | 6.23 | 192 | 80.2/86 | 69.41 | 70.09 | 20.81 |
| 1024+416 pipeline_parse | 87.50 | 5254 | 24.53 | 25.16 | 0.54 | 4.30 | 9.92 | 1.46 | 8.31 | 256 | 83.4/92 | 71.69 | 72.12 | 22.32 |

## Findings

- Best 800+400-requested cascade result: `800+416 pipeline_parse` at `113.09` FPS.
- Best 1024+400-requested cascade result: `1024+416 pipeline_parse` at `87.50` FPS.
- Pipeline parallelism improved both cascades by overlapping stage1 work with stage2 work across adjacent frames.
- 1024+416 remains below 90 FPS in FP16 because concurrent stage1 and stage2 TensorRT execution competes for GPU resources: stage2 latency rises materially in the pipeline run.
- The 800+416 cascade is already above 90 FPS; the 1024+416 cascade would likely require a lighter stage2 classifier, stage2 INT8, DLA/offload if supported, or lower stage2 frequency to exceed 90 without changing stage1 resolution.

## Output Files

- `~/jetson_cascade_benchmark/cascade_benchmark_report.md`
- `~/jetson_cascade_benchmark/cascade_benchmark_results.csv`
- `~/jetson_cascade_benchmark/cascade_benchmark_results.json`
- `~/jetson_cascade_benchmark/scripts/cascade_trt_runner`
- `~/jetson_cascade_benchmark/scripts/cascade_trt_pipeline_runner`
- `~/jetson_cascade_benchmark/logs/`
- `~/jetson_cascade_benchmark/tegrastats/`
