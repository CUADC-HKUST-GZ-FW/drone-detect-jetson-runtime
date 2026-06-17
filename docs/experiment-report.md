# Experiment Report

Status: environment completed and three experiment groups rerun on 2026-06-10.

## Inputs

- Sender: Jetson A.
- Receiver: Jetson B.
- Interface: `eth0`.
- Video source: GStreamer `videotestsrc pattern=snow`.
- Stream duration: 20 seconds per group.
- Sender bitrate request: 8000 kbit/s.
- Model: `yolov26n`, resolved to `yolo26n.pt`.
- Network backend: `simple` TBF + netem, because HTB/IFB are not enabled in the current kernel.

## Environment Completion

- Jetson A and Jetson B project `.venv` now have NVIDIA Jetson PyTorch `2.5.0a0+872d972e41.nv24.08`.
- `torch.cuda.is_available()` is `True` on both Jetsons, CUDA version is 12.6 and device name is `Orin`.
- Jetson A was completed by installing `cuSPARSELt 0.6.2.3` and the NVIDIA PyTorch wheel into the project `.venv`.
- WebUI dependencies `fastapi`, `uvicorn[standard]` and `python-multipart` are installed in both project `.venv` environments.
- Docker CE 29.2.1, Docker Compose 5.0.2 and NVIDIA runtime are available on both Jetsons.
- Compose services `drone-runner-*` and `drone-webui-*` are running on both Jetsons.
- Both Jetsons have `sch_netem`, `sch_tbf` and `cls_u32` installed under `/lib/modules/$(uname -r)/extra/drone-detect/`.
- `tc qdisc add ... netem` add/delete was verified on both Jetsons.
- `tc_apply.py` automatic rollback was verified: 5 second rollback returned `eth0` to default `mq/pfifo_fast`.

## YOLO26n

Jetson A command:

```bash
cd /opt/drone-detect
. .venv/bin/activate
python scripts/run_yolo_video.py --model yolov26n --source assets/test_20s.mp4 --output-dir results/yolo/env_gpu_smoke_jetson_a --device 0 --max-frames 5
```

Observed GPU smoke results:

| Node | Frames | Average inference | Output |
| --- | --- | --- | --- |
| Jetson A | 5 | 53.28 ms | `results/yolo/env_gpu_smoke_ubuntu_20260610_112254/` |
| Jetson B | 5 | 52.70 ms | `results/yolo/env_gpu_smoke_ubuntu_20260610_112302/` |

WebUI-triggered GPU smoke also completed on both nodes:

| Node | Frames | Average inference | Output |
| --- | --- | --- | --- |
| Jetson A | 2 | 96.13 ms | `results/yolo/webui_20260610_035538/` |
| Jetson B | 2 | 92.23 ms | `results/yolo/webui_20260610_035557/` |

## Baseline

Commands:

```bash
# Jetson B
bash experiments/run_01_baseline_stream.sh --role receiver --duration 20 --port 5010 --interface eth0

# Jetson A
bash experiments/run_01_baseline_stream.sh --role sender --dest <JETSON_B_IP> --duration 20 --port 5010 --source testsrc --interface eth0 --pattern snow --bitrate-kbit 8000
```

Observed result:

| Metric | Value |
| --- | --- |
| Sender result dir | `results/baseline/20260610_092711-sender/` |
| Receiver result dir | `results/baseline/20260610_092706-receiver/` |
| Receiver output size | 16400744 bytes |

## Degraded

Policy: `configs/degraded_policy.example.json`.

Applied command:

```bash
sudo python3 scripts/tc_apply.py --config configs/degraded_policy.example.json --set-dst-ip <JETSON_B_IP> --apply --yes --allow-ssh-interface --auto-rollback-seconds 35
```

Policy effect:

- TBF rate: 2 Mbit/s.
- Netem delay: 80 ms.
- Netem loss: 2%.

Observed result:

| Metric | Value |
| --- | --- |
| Sender result dir | `results/baseline/20260610_092741-sender/` |
| Receiver result dir | `results/baseline/20260610_092735-receiver/` |
| Receiver output size | 0 bytes |
| Apply state dir | `results/tc_state/20260610_092739/` |

Conclusion: degraded policy has a visible impact and can break the high-rate test stream.

## Controlled

Policy: `configs/controlled_policy.example.json`.

Applied command:

```bash
sudo python3 scripts/tc_apply.py --config configs/controlled_policy.example.json --set-dst-ip <JETSON_B_IP> --apply --yes --allow-ssh-interface --auto-rollback-seconds 35
```

Policy effect:

- TBF rate: 12 Mbit/s.
- Netem delay: 20 ms.
- No configured loss.

Observed result:

| Metric | Value |
| --- | --- |
| Sender result dir | `results/baseline/20260610_092815-sender/` |
| Receiver result dir | `results/baseline/20260610_092810-receiver/` |
| Receiver output size | 15427656 bytes |
| Apply state dir | `results/tc_state/20260610_092814/` |

Conclusion: controlled policy restores a usable stream close to baseline while still applying a controlled network condition.

## Remaining Limitations

- No real drone footage was found; test source/video is used.
- `ffmpeg` is still missing; GStreamer is the working media path.
- HTB/IFB are not available, so the current real `tc` backend applies interface-wide egress control rather than per-flow priority classes.
- Jetson A has intermittent DNS/registry resolution failures for PyPI and Docker Hub. Current deployment works because the required wheelhouse and Docker image were transferred from Jetson B.
- The current Dockerized design keeps inference in the verified host `.venv` via the privileged runner. A future full inference container should use an L4T/Jetson ML base image or a pinned internal image registry to avoid rebuilding large CUDA/PyTorch stacks on each Jetson.
