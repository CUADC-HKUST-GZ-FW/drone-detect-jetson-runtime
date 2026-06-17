# YOLO Pipeline Release Acceptance Report

## Release

- Release id:
- Date:
- Device:
- Jetson Linux/L4T:
- CUDA:
- TensorRT:
- cuDNN:
- Git commit or source bundle:

## Model Artifacts

| Role | Model id | Requested size | Actual size | Precision | Engine | Accepted |
| --- | --- | --- | --- | --- | --- | --- |
| stage1 |  |  |  |  |  | no |
| stage2 |  |  |  |  |  | no |

## Dataset Artifacts

- Training dataset:
- Validation dataset:
- Test dataset:
- INT8 calibration dataset:
- Stage2 crop dataset:
- Known dataset gaps:

## Accuracy Validation

| Metric | PyTorch | TensorRT FP16 | TensorRT INT8 | Decision |
| --- | ---: | ---: | ---: | --- |
| mAP50-95 |  |  |  |  |
| mAP50 |  |  |  |  |
| precision |  |  |  |  |
| recall |  |  |  |  |

Notes:

```text
Add false positives, false negatives, and per-class concerns here.
```

## Performance Validation

| Mode | Source | FPS | p50 ms | p90 ms | p99 ms | GR3D avg/max | GPU temp max | VDD_IN avg/max |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| strict 1024 single |  |  |  |  |  |  |  |  |
| 1024 cascade |  |  |  |  |  |  |  |  |

Benchmark paths:

```text
Add paths to CSV/JSON/Markdown reports.
```

## Startup Validation

- [ ] Engine deserialize passed.
- [ ] Engine shape matches config.
- [ ] Class names match postprocess.
- [ ] Source opens.
- [ ] GStreamer pipeline prerolls.
- [ ] CUDA device visible.
- [ ] Log path writable.
- [ ] Health reporting works.

## Soak Test

- Duration:
- Source:
- FPS min/avg/max:
- p99 latency max:
- GPU temp max:
- CPU temp max:
- VDD_IN max:
- Memory growth observed:
- Result:

## Known Limitations

```text
List synthetic video limitations, missing camera validation, missing DeepStream, DLA not used, or dataset gaps.
```

## Rollback

- Previous release id:
- Rollback command tested: no
- Rollback notes:

## Final Decision

Decision:

```text
accepted / rejected / accepted for development only
```

Approver:

Notes:

