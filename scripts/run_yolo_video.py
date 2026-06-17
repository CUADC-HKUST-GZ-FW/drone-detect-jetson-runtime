#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import sys
import time
import types
from pathlib import Path


MODEL_ALIASES = {
    "yolov26n": "yolo26n.pt",
    "yolo26n": "yolo26n.pt",
}


def resolve_model(name: str) -> str:
    return MODEL_ALIASES.get(name, name)


def install_torchvision_stub() -> None:
    """Provide the small torchvision surface Ultralytics needs for detect predict."""
    try:
        import torchvision  # noqa: F401
        return
    except Exception:
        for name in list(sys.modules):
            if name == "torchvision" or name.startswith("torchvision."):
                sys.modules.pop(name, None)

    import torch

    original_version = importlib.metadata.version

    def patched_version(package: str) -> str:
        if package.lower() == "torchvision":
            return "0.20.0"
        return original_version(package)

    importlib.metadata.version = patched_version

    tv = types.ModuleType("torchvision")
    ops = types.ModuleType("torchvision.ops")
    roi_align_mod = types.ModuleType("torchvision.ops.roi_align")
    datasets = types.ModuleType("torchvision.datasets")
    transforms = types.ModuleType("torchvision.transforms")
    models = types.ModuleType("torchvision.models")

    def nms(boxes, scores, iou_threshold):
        if boxes.numel() == 0:
            return torch.empty((0,), dtype=torch.long, device=boxes.device)
        x1, y1, x2, y2 = boxes.unbind(1)
        areas = (x2 - x1).clamp(min=0) * (y2 - y1).clamp(min=0)
        order = scores.argsort(descending=True)
        keep = []
        while order.numel() > 0:
            i = order[0]
            keep.append(i)
            if order.numel() == 1:
                break
            rest = order[1:]
            xx1 = torch.maximum(x1[i], x1[rest])
            yy1 = torch.maximum(y1[i], y1[rest])
            xx2 = torch.minimum(x2[i], x2[rest])
            yy2 = torch.minimum(y2[i], y2[rest])
            inter = (xx2 - xx1).clamp(min=0) * (yy2 - yy1).clamp(min=0)
            union = areas[i] + areas[rest] - inter
            iou = inter / union.clamp(min=1e-12)
            order = rest[iou <= iou_threshold]
        return torch.stack(keep).to(dtype=torch.long)

    class RoIAlign:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def __call__(self, *args, **kwargs):
            raise RuntimeError("torchvision RoIAlign stub is not available for SAM models")

    class ImageFolder:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("torchvision ImageFolder stub is not available for classification datasets")

    ops.nms = nms
    ops.RoIAlign = RoIAlign
    roi_align_mod.RoIAlign = RoIAlign
    datasets.ImageFolder = ImageFolder
    tv.__version__ = "0.20.0-stub"
    tv.ops = ops
    tv.datasets = datasets
    tv.transforms = transforms
    tv.models = models

    sys.modules["torchvision"] = tv
    sys.modules["torchvision.ops"] = ops
    sys.modules["torchvision.ops.roi_align"] = roi_align_mod
    sys.modules["torchvision.datasets"] = datasets
    sys.modules["torchvision.transforms"] = transforms
    sys.modules["torchvision.models"] = models


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="yolov26n")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output-dir", default="results/yolo")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default=None)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--max-frames", type=int, default=0)
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = out_dir / "metrics.csv"
    detections_path = out_dir / "detections.jsonl"
    summary_path = out_dir / "summary.json"

    try:
        install_torchvision_stub()
        import cv2
        import psutil
        from ultralytics import YOLO
    except Exception as exc:
        summary_path.write_text(json.dumps({
            "status": "failed_import",
            "error": f"{type(exc).__name__}: {exc}",
            "model_requested": args.model,
            "model_resolved": resolve_model(args.model),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        raise

    model_name = resolve_model(args.model)
    model = YOLO(model_name)
    process = psutil.Process()

    frame_count = 0
    start_time = time.perf_counter()
    total_infer_ms = 0.0

    with metrics_path.open("w", encoding="utf-8", newline="") as metrics_fh, detections_path.open("w", encoding="utf-8") as det_fh:
        writer = csv.DictWriter(metrics_fh, fieldnames=[
            "frame", "time_s", "fps_running", "infer_ms", "detections", "cpu_percent", "rss_mb"
        ])
        writer.writeheader()

        stream = model.predict(
            source=args.source,
            stream=True,
            imgsz=args.imgsz,
            conf=args.conf,
            device=args.device,
            verbose=False,
            save=True,
            project=str(out_dir),
            name="predict",
            exist_ok=True,
        )
        for result in stream:
            now = time.perf_counter()
            frame_count += 1
            speed = getattr(result, "speed", {}) or {}
            infer_ms = float(speed.get("inference", 0.0))
            total_infer_ms += infer_ms
            boxes = getattr(result, "boxes", None)
            det_count = 0 if boxes is None else len(boxes)
            elapsed = max(now - start_time, 1e-9)
            writer.writerow({
                "frame": frame_count,
                "time_s": round(elapsed, 6),
                "fps_running": round(frame_count / elapsed, 4),
                "infer_ms": round(infer_ms, 4),
                "detections": det_count,
                "cpu_percent": process.cpu_percent(interval=None),
                "rss_mb": round(process.memory_info().rss / 1024 / 1024, 2),
            })
            det_fh.write(json.dumps({
                "frame": frame_count,
                "time_s": elapsed,
                "detections": det_count,
                "boxes_xyxy": [] if boxes is None else boxes.xyxy.cpu().tolist(),
                "classes": [] if boxes is None else boxes.cls.cpu().tolist(),
                "conf": [] if boxes is None else boxes.conf.cpu().tolist(),
            }, ensure_ascii=False) + "\n")
            metrics_fh.flush()
            det_fh.flush()
            if args.max_frames and frame_count >= args.max_frames:
                break

    elapsed = max(time.perf_counter() - start_time, 1e-9)
    summary = {
        "status": "ok",
        "model_requested": args.model,
        "model_resolved": model_name,
        "source": args.source,
        "frames": frame_count,
        "elapsed_s": elapsed,
        "fps": frame_count / elapsed,
        "avg_infer_ms": total_infer_ms / frame_count if frame_count else None,
        "metrics": str(metrics_path),
        "detections": str(detections_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
