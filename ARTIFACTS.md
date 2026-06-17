# Artifact Policy

This repository is source, documentation, templates, and small benchmark summaries only.

Do not commit:

- model weights: `*.pt`, `*.pth`
- exported models: `*.onnx`
- TensorRT plans: `*.engine`, `*.raw.engine`, `*.plan`, `*.trt`
- videos, datasets, or calibration images
- raw logs, tegrastats captures, and generated result folders
- compiled native runner binaries
- deployment env files containing real tokens

Recommended production release layout:

```text
/opt/yolo-pipeline/releases/<version>/
  bin/
  config/
  engines/
  metadata/
  manifests/
  reports/
```

Publish large generated artifacts through GitHub Releases, internal object storage, or another artifact store. Build TensorRT engines on the target Jetson or on a machine with exactly matching CUDA/TensorRT versions.
