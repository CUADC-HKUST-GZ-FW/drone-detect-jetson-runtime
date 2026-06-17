# GitHub Release Checklist

Use this checklist before pushing a public branch or creating a release.

## Source Hygiene

- `git status --short` contains only intentional source/docs/config changes.
- `git ls-files` contains no model weights, engines, ONNX files, videos, datasets, virtualenvs, logs, or generated results.
- Real deployment env files are ignored; only `*.env.example` files are tracked.
- No private IPs, tokens, hostnames, private keys, or shell history are tracked.
- Native build outputs are ignored.

## Validation

```bash
python3 -m pytest
git ls-files | grep -E '\.(pt|onnx|engine|raw\.engine|mp4|zip|tar|gz)$' && exit 1 || true
```

On target Jetson/AGX:

```bash
make -C native -j"$(nproc)"
python3 scripts/export_yolo_engine.py --model yolo26n.pt --imgsz 1024 --device 0 --half true --workspace 4
python3 scripts/strip_ultralytics_engine.py models/trt/yolo26n_1024_fp16_ultralytics.engine --verify
```

## Artifact Release Notes

For any artifact published outside Git, include:

- filename
- SHA256
- target Jetson/AGX model
- JetPack/L4T
- CUDA
- TensorRT
- source model and export command
- whether the input policy is strict square or fast 16:9 caps
