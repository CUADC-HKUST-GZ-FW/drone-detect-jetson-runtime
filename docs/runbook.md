# Runbook

All commands run from:

```bash
cd /opt/drone-detect
```

## 1. Inventory

```bash
bash scripts/inventory.sh --node jetson-a
bash scripts/inventory.sh --node jetson-b
```

Outputs go to `results/inventory/<node>-<timestamp>/`.

## 2. Test Video

If no drone video is available:

```bash
bash scripts/make_test_video.sh --duration 60 --output assets/test_60s.mp4
```

## 3. Baseline Stream

Start receiver first:

```bash
mkdir -p results/baseline
bash scripts/start_receiver.sh --port 5000 --duration 60 --output results/baseline/received.ts 2>&1 | tee results/baseline/receiver.log
```

Start sender:

```bash
bash scripts/start_sender.sh --dest <JETSON_B_IP> --port 5000 --duration 60 --source testsrc 2>&1 | tee results/baseline/sender.log
```

## 4. Metrics

Run metrics in a separate terminal during sender/receiver:

```bash
python3 scripts/collect_metrics.py --interface eth0 --duration 60 --output results/baseline/metrics.jsonl
```

## 5. YOLO26n

```bash
. .venv/bin/activate
python scripts/run_yolo_video.py --model yolov26n --source assets/test_60s.mp4 --output-dir results/yolo --device 0
```

The model alias `yolov26n` resolves to `yolo26n.pt`.

## 5B. WebUI / Compose

Start on Jetson A:

```bash
cd /opt/drone-detect
NODE_ROLE=sender HOST_PROJECT_DIR=/opt/drone-detect DRONE_INTERFACE=eth0 docker compose up -d
```

Start on Jetson B:

```bash
cd /opt/drone-detect
NODE_ROLE=receiver HOST_PROJECT_DIR=/opt/drone-detect DRONE_INTERFACE=eth0 docker compose up -d
```

Open the WebUI:

```text
http://<JETSON_IP>:18080
```

Useful checks:

```bash
docker compose ps
curl -fsS http://127.0.0.1:18080/api/status | python3 -m json.tool
curl -fsS http://127.0.0.1:18081/api/status | python3 -m json.tool
```

Stop:

```bash
docker compose down
```

The WebUI exposes visual controls for node status, video sender/receiver start, YOLO GPU smoke, `tc` dry-run/apply/status/clear and result browsing.

Security note: the WebUI has no built-in authentication and the runner can execute privileged network-control actions. Use it only on the trusted lab network, or place it behind SSH tunneling, VPN or an authenticated reverse proxy before wider exposure.

If Jetson A cannot reach Docker Hub or PyPI, build the image and wheelhouse on Jetson B, then transfer:

```bash
# Jetson B
docker save drone-detect-webui:local -o .cache/drone-detect-webui-local.tar

# Jetson A
docker load -i .cache/drone-detect-webui-local.tar
```

## 6. Network Policy

Check kernel traffic-control support before real apply:

```bash
for k in sch_netem sch_htb sch_tbf cls_u32 ifb; do modprobe -n -v "$k" || true; done
```

The completed environment has `sch_netem`, `sch_tbf` and `cls_u32` installed under `/lib/modules/$(uname -r)/extra/drone-detect/`. HTB/IFB are still unavailable, so the checked-in example policies use `backend: simple`.

Dry-run:

```bash
python3 scripts/tc_apply.py --config configs/degraded_policy.example.json --set-dst-ip <JETSON_B_IP> --dry-run
```

Apply:

```bash
sudo python3 scripts/tc_apply.py --config configs/degraded_policy.example.json --set-dst-ip <JETSON_B_IP> --apply --yes --allow-ssh-interface
```

Status:

```bash
python3 scripts/tc_apply.py --interface eth0 --status
```

Confirm rollback guard:

```bash
python3 scripts/tc_apply.py --confirm <TOKEN>
```

Clear:

```bash
sudo python3 scripts/tc_apply.py --interface eth0 --clear --yes
```

## 7. Experiment Order

1. Run baseline without `tc`.
2. Run degraded with `configs/degraded_policy.example.json`.
3. Run controlled with `configs/controlled_policy.example.json`.
4. Fill `docs/experiment-report.md` with observed metrics and limitations.
