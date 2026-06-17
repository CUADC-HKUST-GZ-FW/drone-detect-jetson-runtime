# Benchmark Reports

This directory keeps lightweight sanitized benchmark summaries from the Jetson Orin NX optimization work.

Included:

- single-model 800 FP16 summary
- single-model 1024 FP16 summary
- cascade summary
- wall-FPS comparison summary

Not included:

- TensorRT `.engine` or `.raw.engine` files
- model weights
- videos or datasets
- raw `logs/` output
- raw `tegrastats/` output
- compiled C++ runner binaries

The reports may reference example deployment paths such as `/home/jetson/...` or `/opt/yolo-pipeline/...`; these are placeholders for the target Jetson deployment.
