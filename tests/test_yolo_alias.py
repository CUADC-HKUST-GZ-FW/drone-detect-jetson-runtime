import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_yolo_video


def test_yolov26n_alias():
    assert run_yolo_video.resolve_model("yolov26n") == "yolo26n.pt"
    assert run_yolo_video.resolve_model("yolo26n") == "yolo26n.pt"
    assert run_yolo_video.resolve_model("custom.pt") == "custom.pt"

