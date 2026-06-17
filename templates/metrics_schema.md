# Metrics Schema

Metrics should be emitted as JSON Lines at a fixed interval.

## Required Fields

```text
ts
release_id
config_hash
source
frames_read
frames_processed
frames_failed
wall_fps
latency_ms_mean
latency_ms_p50
latency_ms_p90
latency_ms_p99
read_ms_mean
preprocess_ms_mean
infer_ms_mean
postprocess_ms_mean
gr3d_avg_pct
gr3d_max_pct
ram_used_mb_avg
ram_used_mb_max
gpu_temp_c_avg
gpu_temp_c_max
cpu_temp_c_avg
cpu_temp_c_max
vdd_in_w_avg
vdd_in_w_max
health_state
```

## Cascade Fields

```text
stage1_infer_ms_mean
stage2_infer_ms_mean
stage1_selected_conf_mean
roi_area_ratio_mean
fallback_count
stage2_processed_frames
```

## Naming Rules

- Use `_ms` for milliseconds.
- Use `_pct` for percentages.
- Use `_c` for Celsius.
- Use `_w` for watts.
- Use `_mb` for megabytes.
- Use `avg`, `max`, `mean`, `p50`, `p90`, `p99` consistently.

## Reporting Notes

`wall_fps` is end-to-end throughput. It includes source read, preprocessing, inference, postprocessing, and result handling.

`infer_ms` is model inference time only. It must not be used as the production end-to-end FPS by itself.

`trtexec --noDataTransfers` is a raw TensorRT probe. It is useful for estimating engine capability but is not a video pipeline FPS result.

