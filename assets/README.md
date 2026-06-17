# Assets

Large videos are intentionally not committed.

If no drone video is available, generate a test video:

```bash
bash scripts/make_test_video.sh --duration 60 --output assets/test_60s.mp4
```

To use real drone footage, copy it into this directory and pass it to:

```bash
bash scripts/start_sender.sh --dest <JETSON_B_IP> --source assets/<drone-video>.mp4
python3 scripts/run_yolo_video.py --model yolov26n --source assets/<drone-video>.mp4 --output-dir results/yolo
```

