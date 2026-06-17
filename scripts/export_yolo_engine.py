#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from run_yolo_video import install_torchvision_stub


def parse_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Export YOLO model to a target-Jetson TensorRT engine.")
    parser.add_argument("--model", default="yolo26n.pt")
    parser.add_argument("--imgsz", type=int, default=1024)
    parser.add_argument("--device", default="0")
    parser.add_argument("--half", default="true")
    parser.add_argument("--workspace", type=float, default=4.0)
    parser.add_argument("--simplify", default="false")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    install_torchvision_stub()
    from ultralytics import YOLO

    model_path = Path(args.model).resolve()
    if not model_path.exists():
        raise FileNotFoundError(model_path)

    engine_output = Path(args.output or f"models/trt/{model_path.stem}_{args.imgsz}_fp16_ultralytics.engine")
    engine_output.parent.mkdir(parents=True, exist_ok=True)

    model = YOLO(str(model_path))
    exported = Path(
        model.export(
            format="engine",
            imgsz=args.imgsz,
            half=parse_bool(args.half),
            device=args.device,
            workspace=args.workspace,
            dynamic=False,
            simplify=parse_bool(args.simplify),
            verbose=False,
        )
    )
    if not exported.exists():
        raise FileNotFoundError(f"Ultralytics reported {exported}, but the file does not exist")
    if exported.resolve() != engine_output.resolve():
        shutil.copy2(exported, engine_output)

    print(engine_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
