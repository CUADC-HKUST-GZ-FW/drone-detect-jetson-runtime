# 10 Release Acceptance Checklist

This checklist defines when a YOLO model or pipeline change is ready to run outside development.

## Release Inputs

- [ ] Source model `*.pt`
- [ ] Dataset manifest
- [ ] Training run metadata
- [ ] Validation metrics
- [ ] Export commands
- [ ] Ultralytics engine `*.engine`
- [ ] Raw TensorRT plan `*.raw.engine`
- [ ] Engine metadata JSON
- [ ] Runtime config
- [ ] Model manifest
- [ ] Benchmark report
- [ ] Tegrastats summary
- [ ] Rollback target

## Dataset Gates

- [ ] Class ids in `data.yaml` are stable.
- [ ] Train/val/test split is scene-separated for video data.
- [ ] Test set is not used for tuning thresholds.
- [ ] Stage2 crop dataset matches production crop distribution.
- [ ] Hard negatives are included.
- [ ] Label quality review is recorded.
- [ ] Data drift examples are either included or listed as known gaps.

## Model Quality Gates

- [ ] PyTorch validation completed.
- [ ] TensorRT validation completed.
- [ ] FP16 accuracy difference is acceptable.
- [ ] INT8 accuracy difference is acceptable, if INT8 is used.
- [ ] Per-class precision/recall reviewed.
- [ ] Confusion matrix reviewed.
- [ ] False-positive and false-negative examples reviewed.
- [ ] Stage1 recall is high enough for cascade.
- [ ] Full cascade end-to-end quality is checked.

## Engine Gates

- [ ] Engine built on target Jetson or matching stack.
- [ ] TensorRT/CUDA/L4T versions recorded.
- [ ] Engine metadata saved.
- [ ] Raw TensorRT plan generated.
- [ ] Binding names and shapes verified.
- [ ] Requested size and actual size recorded.
- [ ] `requested400_actual416` naming used where applicable.
- [ ] `trtexec` or C++ runner smoke test passed.

## Pipeline Gates

- [ ] Strict `1024x1024` path uses square appsink/C++ input.
- [ ] GStreamer hardware decoder smoke test passed.
- [ ] `nvvidconv` path works.
- [ ] `nvcompositor` path works when strict square canvas is required.
- [ ] C++ runner reuses TensorRT context and buffers.
- [ ] No per-frame allocation in hot path.
- [ ] No per-frame stdout logging in production profile.
- [ ] Debug drawing/saving is disabled for benchmark and production.
- [ ] Result sink is tested.

## Performance Gates

Record both synthetic benchmark and target source benchmark.

Minimum required fields:

- [ ] source URI
- [ ] source resolution and FPS
- [ ] model id
- [ ] precision
- [ ] requested and actual input sizes
- [ ] warmup seconds
- [ ] measurement seconds
- [ ] frames processed
- [ ] wall FPS
- [ ] p50/p90/p99 latency
- [ ] stage timing breakdown
- [ ] GR3D avg/max
- [ ] GPU/CPU temperature avg/max
- [ ] VDD_IN avg/max

Current known baselines:

```text
strict 1024 single-model C++ path:      about 103 FPS
800 + requested400_actual416 cascade:   about 113 FPS
1024 + requested400_actual416 cascade:  about 87.5 FPS
```

## Soak Test

Run at least 10 minutes on the target source or a representative video.

Pass criteria:

- [ ] FPS remains within expected range.
- [ ] p99 latency does not drift upward continuously.
- [ ] GPU temperature stays below configured limit.
- [ ] No source reconnect loop.
- [ ] No TensorRT errors.
- [ ] No memory growth indicating a leak.
- [ ] Logs and metrics remain parseable.

## Deployment Gates

- [ ] Release directory is immutable after acceptance.
- [ ] `current` symlink points to accepted release.
- [ ] `previous` symlink points to rollback release.
- [ ] systemd service file references `current`.
- [ ] Startup validation exits non-zero on hard failure.
- [ ] Health endpoint or health file is available.
- [ ] Restart policy is configured.
- [ ] Rollback command tested.

## Agent Stop Conditions

An agent must stop and report when:

- engine shape mismatches config
- requested `400` becomes actual `416` and naming/reporting has not been updated
- strict `1024x1024` cannot be preserved
- INT8 export succeeds but accuracy validation is missing
- FPS benchmark excludes decode when the goal is end-to-end wall FPS
- DeepStream installation is required but not explicitly approved
- changing resolution, precision, frame skipping, or model family is needed to meet target FPS

## Acceptance Report

Use:

```text
templates/acceptance_report_template.md
```

Attach it to the release directory and include:

- release id
- model ids
- dataset ids
- benchmark paths
- known limitations
- rollback target
- final decision

