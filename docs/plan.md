# Implementation Plan

## Phase 1: Audit and Documentation

Completed:

- Confirmed SSH access to both Jetsons.
- Audited OS, L4T, Python, GStreamer, `tc`, `iperf3`, interfaces and project directories.
- Wrote this plan before making system-level changes.

## Phase 2: Project Layout

Create reproducible scripts under `/opt/drone-detect`:

- `scripts/inventory.sh` for repeatable environment audit.
- `scripts/start_sender.sh` and `scripts/start_receiver.sh` for RTP/H.264 video streaming.
- `scripts/run_yolo_video.py` for YOLO26n detection metrics.
- `scripts/tc_apply.py` for JSON to `tc` conversion, dry-run, apply, status, clear and rollback.
- `scripts/collect_metrics.py` for CPU, memory, network, `tc` and Jetson telemetry.

## Phase 3: Minimal Environment Setup

Use project-local `.venv` where possible:

```bash
cd /opt/drone-detect
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install ultralytics pyyaml psutil
```

Do not upgrade JetPack, CUDA or system Python. If Jetson A cannot install a suitable PyTorch wheel, record the failure and run YOLO on the available node as a fallback while keeping the target command for Jetson A documented.

## Phase 4: Video Baseline

Generate a local test video if no drone footage is available:

```bash
bash scripts/make_test_video.sh --duration 60 --output assets/test_60s.mp4
```

Run Jetson B receiver first, then Jetson A sender. Save logs and received stream under `results/baseline/`.

## Phase 5: YOLO26n

Run YOLO26n against the test video on Jetson A:

```bash
python3 scripts/run_yolo_video.py --model yolov26n --source assets/test_60s.mp4 --output-dir results/yolo --device 0
```

Completed update: both Jetsons now use the NVIDIA Jetson PyTorch wheel in the project `.venv` and can run YOLO26n with CUDA device `0`.

## Phase 5B: Dockerized WebUI Management

Completed:

- `compose.yaml` manages both `drone-runner` and `drone-webui`.
- `drone-runner` runs privileged with host PID/network and uses `nsenter` to execute the already verified host project commands.
- `drone-webui` serves a persistent no-card enterprise-style admin panel on port `18080`.
- The runner API is exposed locally on port `18081`.
- Both services use `restart: unless-stopped`.

## Phase 6: Network Control

Use dry-run first:

```bash
python3 scripts/tc_apply.py --config configs/degraded_policy.example.json --dry-run
```

Apply only with rollback:

```bash
sudo python3 scripts/tc_apply.py --config configs/degraded_policy.example.json --apply --yes --allow-ssh-interface
```

Completed environment: `sch_netem`, `sch_tbf` and `cls_u32` were built and installed on both Jetsons. The current real apply path uses `backend: simple` TBF + netem. HTB/IFB remain unavailable.

Confirm or allow rollback:

```bash
python3 scripts/tc_apply.py --confirm <TOKEN>
```

## Phase 7: Experiments

Run three 60 second experiments:

- `baseline`: no network impairment.
- `degraded`: apply bandwidth/delay/loss policy.
- `controlled`: apply a different policy that reserves more bandwidth for video.

Current status:

- Baseline stream completed with test source.
- YOLO26n smoke completed on Jetson A and Jetson B.
- Degraded and controlled real apply completed with simple backend.

Each result directory should include:

- `commands.log`
- `sender.log`
- `receiver.log`
- `metrics.jsonl`
- `tc_status_before.txt`
- `tc_status_after.txt`
- `summary.md`
