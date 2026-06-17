#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from ultralytics import YOLO


HOME = Path.home()
ROOT = HOME / "jetson_wallfps_optimization"
LOGS = ROOT / "logs"
TEGR = ROOT / "tegrastats"
ENGINES = ROOT / "engines"
SCRIPTS = ROOT / "scripts"
REPORT = ROOT / "wallfps_optimization_report.md"
CSV_PATH = ROOT / "wallfps_results.csv"
JSON_PATH = ROOT / "wallfps_results.json"
JSONL_PATH = ROOT / "wallfps_results.jsonl"

VIDEO = HOME / "jetson_benchmark_assets/videos/benchmark_5min_720p30_coco_val2017_synthetic.mp4"
VIDEO_1080 = HOME / "jetson_benchmark_assets/videos/benchmark_5min_1080p30_coco_val2017_synthetic.mp4"
CALIB_YAML = HOME / "jetson_benchmark_assets/coco_val2017_calib.yaml"
MODELS_DIR = HOME / "jetson_benchmark_assets/models"
YOLO_BIN = HOME / "venvs/yolo-jetson/bin/yolo"

WARMUP_SEC = float(os.environ.get("WALLFPS_WARMUP_SEC", "10"))
MEASURE_SEC = float(os.environ.get("WALLFPS_MEASURE_SEC", "120"))
IMGSZ = 640
CONF = 0.25
IOU = 0.70
RING_FRAMES = int(os.environ.get("WALLFPS_RING_FRAMES", "300"))


def ensure_dirs() -> None:
    for path in [ROOT, LOGS, TEGR, ENGINES, SCRIPTS]:
        path.mkdir(parents=True, exist_ok=True)


def sh(cmd: str, timeout: int | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(
            ["bash", "-lc", cmd],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return p.returncode, p.stdout
    except subprocess.TimeoutExpired as e:
        return 124, (e.stdout or "") + f"\n[TIMEOUT after {timeout}s]"
    except Exception as e:
        return 1, repr(e)


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    k = (len(vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(vals[int(k)])
    return float(vals[f] * (c - k) + vals[c] * (k - f))


def stat_ms(values: list[float]) -> dict:
    if not values:
        return {
            "mean_ms": None,
            "p50_ms": None,
            "p90_ms": None,
            "p99_ms": None,
            "min_ms": None,
            "max_ms": None,
        }
    return {
        "mean_ms": statistics.fmean(values),
        "p50_ms": statistics.median(values),
        "p90_ms": percentile(values, 90),
        "p99_ms": percentile(values, 99),
        "min_ms": min(values),
        "max_ms": max(values),
    }


def start_tegrastats(path: Path) -> subprocess.Popen:
    return subprocess.Popen(
        ["tegrastats", "--interval", "1000", "--logfile", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def stop_process(proc: subprocess.Popen | None) -> None:
    if not proc:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def parse_tegrastats(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    text = path.read_text(encoding="utf-8", errors="replace")
    gr3d = [float(x) for x in re.findall(r"GR3D_FREQ\s+(\d+)%", text)]
    ram = [float(x) for x in re.findall(r"RAM\s+(\d+)/", text)]
    vdd = [float(x) for x in re.findall(r"VDD_IN\s+(\d+)mW", text)]
    cpu_utils = [
        float(x)
        for group in re.findall(r"\bCPU\s+\[([^\]]+)\]", text)
        for x in re.findall(r"(\d+)%@", group)
    ]

    def simple(vals: list[float]) -> dict:
        if not vals:
            return {"avg": None, "max": None, "min": None}
        return {"avg": sum(vals) / len(vals), "max": max(vals), "min": min(vals)}

    def temps(name: str) -> dict:
        return simple([float(x) for x in re.findall(rf"{name}@([0-9.]+)C", text)])

    return {
        "exists": True,
        "samples": len([ln for ln in text.splitlines() if ln.strip()]),
        "gr3d": simple(gr3d),
        "ram_used_mb": simple(ram),
        "cpu_util_pct": simple(cpu_utils),
        "gpu_temp_c": temps("gpu"),
        "cpu_temp_c": temps("cpu"),
        "tj_temp_c": temps("tj"),
        "vdd_in_mw": simple(vdd),
        "nvdla_fields_seen": "NVDLA" in text.upper(),
    }


def video_info(path: Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            return {"opened": False, "path": str(path)}
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        return {
            "opened": True,
            "path": str(path),
            "fps": fps,
            "frames": frames,
            "width": width,
            "height": height,
            "duration_sec": frames / fps if fps else None,
        }
    finally:
        cap.release()


def copy_or_build_engine(model: str, precision: str) -> tuple[Path, float, str]:
    stem = Path(model).stem
    dst = ENGINES / f"{stem}_640_{precision}.engine"
    if dst.exists():
        return dst, 0.0, "existing_local"

    candidates = [
        HOME / f"jetson_yolo_formal_benchmark_full/engines/{stem}_640_{precision}.engine",
        HOME / f"jetson_yolo_formal_benchmark_full/work/weights/{stem}_640_{precision}.engine",
        HOME / f"jetson_yolo_formal_benchmark_sanity/engines/{stem}_640_{precision}.engine",
        HOME / f"jetson_yolo_formal_benchmark_sanity/work/weights/{stem}_640_{precision}.engine",
    ]
    for src in candidates:
        if src.exists():
            shutil.copy2(src, dst)
            return dst, 0.0, f"copied:{src}"

    pt = MODELS_DIR / model
    if not pt.exists():
        raise FileNotFoundError(f"missing model and engine: {model}")
    cmd = [
        str(YOLO_BIN),
        "export",
        "task=detect",
        f"model={pt}",
        "format=engine",
        f"imgsz={IMGSZ}",
        "device=0",
        "workspace=4",
        "verbose=False",
    ]
    if precision == "int8":
        cmd += ["int8=True", f"data={CALIB_YAML}", "batch=1"]
    elif precision == "fp16":
        cmd += ["half=True"]
    else:
        raise ValueError(precision)
    log_path = LOGS / f"{stem}_640_{precision}_export.log"
    t0 = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as fh:
        p = subprocess.run(cmd, cwd=str(ENGINES), stdout=fh, stderr=subprocess.STDOUT, text=True)
    sec = time.perf_counter() - t0
    built = ENGINES / f"{stem}.engine"
    if p.returncode != 0 or not built.exists():
        raise RuntimeError(f"engine export failed for {model}/{precision}, rc={p.returncode}, log={log_path}")
    built.rename(dst)
    return dst, sec, "built"


def predict_kwargs() -> dict:
    return {
        "imgsz": IMGSZ,
        "device": 0,
        "conf": CONF,
        "iou": IOU,
        "verbose": False,
        "save": False,
        "show": False,
    }


def consume_result_speed(results) -> float | None:
    if not results:
        return None
    try:
        speed = getattr(results[0], "speed", None) or {}
        val = speed.get("inference")
        return float(val) if val is not None else None
    except Exception:
        return None


def run_ultralytics_video(model: YOLO, video: Path, seconds: float, warmup: bool = False) -> dict:
    frames = 0
    failed = 0
    wall_ms: list[float] = []
    infer_ms: list[float] = []
    end = time.perf_counter() + seconds
    last = time.perf_counter()
    while time.perf_counter() < end:
        try:
            for res in model.predict(source=str(video), stream=True, **predict_kwargs()):
                now = time.perf_counter()
                if not warmup:
                    wall_ms.append((now - last) * 1000.0)
                    speed = getattr(res, "speed", None) or {}
                    if speed.get("inference") is not None:
                        infer_ms.append(float(speed["inference"]))
                last = now
                frames += 1
                if now >= end:
                    break
        except Exception:
            failed += 1
            break
    return {"frames": frames, "failed": failed, "wall_ms": wall_ms, "predict_ms": infer_ms, "read_ms": []}


def open_cv_capture(video: Path) -> cv2.VideoCapture:
    return cv2.VideoCapture(str(video))


def gst_pipelines(video: Path) -> list[str]:
    loc = str(video)
    return [
        f"filesrc location={loc} ! qtdemux ! h264parse ! nvv4l2decoder enable-max-performance=1 ! nvvidconv ! video/x-raw,format=BGRx ! videoconvert ! video/x-raw,format=BGR ! appsink drop=true sync=false max-buffers=2",
        f"filesrc location={loc} ! qtdemux ! h264parse ! nvv4l2decoder enable-max-performance=1 ! nvvidconv ! video/x-raw,format=RGBA ! videoconvert ! video/x-raw,format=BGR ! appsink drop=true sync=false max-buffers=2",
        f"filesrc location={loc} ! qtdemux ! h264parse ! nvv4l2decoder ! nvvidconv ! video/x-raw,format=BGRx ! videoconvert ! video/x-raw,format=BGR ! appsink drop=true sync=false max-buffers=2",
    ]


def open_gst_capture(video: Path) -> tuple[cv2.VideoCapture | None, str]:
    for pipe in gst_pipelines(video):
        cap = cv2.VideoCapture(pipe, cv2.CAP_GSTREAMER)
        if cap.isOpened():
            ok, _ = cap.read()
            if ok:
                cap.release()
                return cv2.VideoCapture(pipe, cv2.CAP_GSTREAMER), pipe
        cap.release()
    return None, ""


def run_capture_loop(
    model: YOLO,
    cap_factory: Callable[[], cv2.VideoCapture],
    seconds: float,
    warmup: bool = False,
) -> dict:
    cap = cap_factory()
    if not cap.isOpened():
        return {"frames": 0, "failed": 1, "wall_ms": [], "predict_ms": [], "read_ms": [], "error": "capture_open_failed"}
    frames = 0
    failed = 0
    wall_ms: list[float] = []
    predict_ms: list[float] = []
    read_ms: list[float] = []
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        frame_start = time.perf_counter()
        r0 = time.perf_counter()
        ok, frame = cap.read()
        r1 = time.perf_counter()
        if not ok:
            cap.release()
            cap = cap_factory()
            if not cap.isOpened():
                failed += 1
                break
            ok, frame = cap.read()
            r1 = time.perf_counter()
            if not ok:
                failed += 1
                break
        p0 = time.perf_counter()
        results = model.predict(source=frame, **predict_kwargs())
        p1 = time.perf_counter()
        if not warmup:
            read_ms.append((r1 - r0) * 1000.0)
            predict_ms.append((p1 - p0) * 1000.0)
            wall_ms.append((p1 - frame_start) * 1000.0)
        frames += 1
    cap.release()
    return {"frames": frames, "failed": failed, "wall_ms": wall_ms, "predict_ms": predict_ms, "read_ms": read_ms}


def load_frame_ring(video: Path, limit: int) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(video))
    frames: list[np.ndarray] = []
    while len(frames) < limit:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    if not frames:
        raise RuntimeError(f"could not predecode frames from {video}")
    return frames


def run_ring_loop(model: YOLO, frames: list[np.ndarray], seconds: float, warmup: bool = False) -> dict:
    idx = 0
    count = 0
    wall_ms: list[float] = []
    predict_ms: list[float] = []
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        frame = frames[idx]
        idx = (idx + 1) % len(frames)
        t0 = time.perf_counter()
        results = model.predict(source=frame, **predict_kwargs())
        t1 = time.perf_counter()
        if not warmup:
            wall_ms.append((t1 - t0) * 1000.0)
            predict_ms.append((t1 - t0) * 1000.0)
        count += 1
    return {"frames": count, "failed": 0, "wall_ms": wall_ms, "predict_ms": predict_ms, "read_ms": []}


def run_synthetic_loop(model: YOLO, shape: tuple[int, int, int], seconds: float, warmup: bool = False) -> dict:
    frame = np.zeros(shape, dtype=np.uint8)
    cv2.putText(frame, "synthetic", (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 255, 0), 3)
    return run_ring_loop(model, [frame], seconds, warmup=warmup)


def summarize_run(
    model_name: str,
    precision: str,
    engine_path: Path,
    input_mode: str,
    input_path: str,
    run_data: dict,
    tegra_log: Path,
    wall_start: float,
    wall_end: float,
    notes: str,
    extra: dict | None = None,
) -> dict:
    wall_sec = wall_end - wall_start
    frames = int(run_data.get("frames", 0))
    wall_stats = stat_ms(run_data.get("wall_ms", []))
    pred_stats = stat_ms(run_data.get("predict_ms", []))
    read_stats = stat_ms(run_data.get("read_ms", []))
    row = {
        "model_name": model_name,
        "precision": precision,
        "engine_path": str(engine_path),
        "input_path": input_path,
        "input_mode": input_mode,
        "video_resolution": "1280x720",
        "target_imgsz": IMGSZ,
        "warmup_sec": WARMUP_SEC,
        "measure_sec": MEASURE_SEC,
        "frames_processed": frames,
        "wall_sec": wall_sec,
        "wall_fps": frames / wall_sec if wall_sec > 0 else None,
        "mean_wall_ms": wall_stats["mean_ms"],
        "p50_wall_ms": wall_stats["p50_ms"],
        "p90_wall_ms": wall_stats["p90_ms"],
        "p99_wall_ms": wall_stats["p99_ms"],
        "mean_read_ms": read_stats["mean_ms"],
        "mean_predict_ms": pred_stats["mean_ms"],
        "p50_predict_ms": pred_stats["p50_ms"],
        "p90_predict_ms": pred_stats["p90_ms"],
        "p99_predict_ms": pred_stats["p99_ms"],
        "failed_frames": int(run_data.get("failed", 0)),
        "notes": notes,
        "tegrastats_log": str(tegra_log),
        "tegrastats": parse_tegrastats(tegra_log),
    }
    if extra:
        row.update(extra)
    return row


def run_experiment(model_name: str, precision: str, engine_path: Path, input_mode: str, frames_ring: list[np.ndarray] | None = None) -> dict:
    label = f"{Path(model_name).stem}_{precision}_{input_mode}"
    tegra_log = TEGR / f"{label}.log"
    model = YOLO(str(engine_path), task="detect")
    notes = "minimal_result_handling; save/show/verbose disabled; boxes not accessed"
    extra: dict = {}

    if input_mode == "baseline_ultralytics_video":
        run_ultralytics_video(model, VIDEO, WARMUP_SEC, warmup=True)
        proc = start_tegrastats(tegra_log)
        t0 = time.perf_counter()
        data = run_ultralytics_video(model, VIDEO, MEASURE_SEC, warmup=False)
        t1 = time.perf_counter()
        stop_process(proc)
    elif input_mode == "opencv_video_capture":
        run_capture_loop(model, lambda: open_cv_capture(VIDEO), WARMUP_SEC, warmup=True)
        proc = start_tegrastats(tegra_log)
        t0 = time.perf_counter()
        data = run_capture_loop(model, lambda: open_cv_capture(VIDEO), MEASURE_SEC, warmup=False)
        t1 = time.perf_counter()
        stop_process(proc)
    elif input_mode == "gstreamer_hwdecode_appsink":
        rc, out = sh(f"gst-launch-1.0 -q filesrc location='{VIDEO}' ! qtdemux ! h264parse ! nvv4l2decoder enable-max-performance=1 ! fakesink sync=false", timeout=45)
        (LOGS / f"{label}_gst_launch.log").write_text(out, encoding="utf-8")
        cap, pipe = open_gst_capture(VIDEO)
        if cap is None:
            return summarize_run(
                model_name,
                precision,
                engine_path,
                input_mode,
                str(VIDEO),
                {"frames": 0, "failed": 1, "wall_ms": [], "predict_ms": [], "read_ms": []},
                tegra_log,
                time.perf_counter(),
                time.perf_counter(),
                f"FAILED: OpenCV CAP_GSTREAMER could not open appsink pipeline; gst-launch rc={rc}; see logs",
                {"gst_launch_rc": rc, "gst_pipeline": ""},
            )
        cap.release()
        notes += "; nvv4l2decoder+nvvidconv+appsink; not DeepStream zero-copy"
        extra["gst_launch_rc"] = rc
        extra["gst_pipeline"] = pipe
        run_capture_loop(model, lambda: cv2.VideoCapture(pipe, cv2.CAP_GSTREAMER), WARMUP_SEC, warmup=True)
        proc = start_tegrastats(tegra_log)
        t0 = time.perf_counter()
        data = run_capture_loop(model, lambda: cv2.VideoCapture(pipe, cv2.CAP_GSTREAMER), MEASURE_SEC, warmup=False)
        t1 = time.perf_counter()
        stop_process(proc)
    elif input_mode == "predecoded_frame_ring":
        assert frames_ring is not None
        notes += f"; predecoded_ring_frames={len(frames_ring)}; decode excluded from measurement"
        run_ring_loop(model, frames_ring, WARMUP_SEC, warmup=True)
        proc = start_tegrastats(tegra_log)
        t0 = time.perf_counter()
        data = run_ring_loop(model, frames_ring, MEASURE_SEC, warmup=False)
        t1 = time.perf_counter()
        stop_process(proc)
    elif input_mode == "synthetic_numpy_frame_loop":
        notes += "; synthetic_numpy_frame; no decode and no real image diversity"
        shape = (720, 1280, 3)
        run_synthetic_loop(model, shape, WARMUP_SEC, warmup=True)
        proc = start_tegrastats(tegra_log)
        t0 = time.perf_counter()
        data = run_synthetic_loop(model, shape, MEASURE_SEC, warmup=False)
        t1 = time.perf_counter()
        stop_process(proc)
    else:
        raise ValueError(input_mode)

    return summarize_run(model_name, precision, engine_path, input_mode, str(VIDEO), data, tegra_log, t0, t1, notes, extra)


def run_trtexec_probe(model_name: str, precision: str, engine_path: Path) -> dict:
    label = f"{Path(model_name).stem}_{precision}_trtexec_raw_no_data_transfers"
    log_path = LOGS / f"{label}.log"
    tegra_log = TEGR / f"{label}.log"
    trtexec = shutil.which("trtexec")
    if not trtexec:
        return {
            "model_name": model_name,
            "precision": precision,
            "engine_path": str(engine_path),
            "input_mode": "trtexec_raw_no_data_transfers",
            "frames_processed": 0,
            "wall_fps": None,
            "notes": "trtexec not found in PATH",
            "failed_frames": 1,
        }
    cmd = [
        trtexec,
        f"--loadEngine={engine_path}",
        "--duration=120",
        "--warmUp=10000",
        "--useSpinWait",
        "--useCudaGraph",
        "--noDataTransfers",
    ]
    proc = start_tegrastats(tegra_log)
    t0 = time.perf_counter()
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    t1 = time.perf_counter()
    stop_process(proc)
    log_path.write_text(p.stdout, encoding="utf-8")
    throughput = None
    m = re.search(r"Throughput:\s*([0-9.]+)\s*qps", p.stdout)
    if m:
        throughput = float(m.group(1))
    return {
        "model_name": model_name,
        "precision": precision,
        "engine_path": str(engine_path),
        "input_path": str(engine_path),
        "input_mode": "trtexec_raw_no_data_transfers",
        "video_resolution": "none",
        "target_imgsz": IMGSZ,
        "warmup_sec": 10,
        "measure_sec": 120,
        "frames_processed": None,
        "wall_sec": t1 - t0,
        "wall_fps": throughput,
        "mean_wall_ms": None,
        "p50_wall_ms": None,
        "p90_wall_ms": None,
        "p99_wall_ms": None,
        "mean_read_ms": None,
        "mean_predict_ms": None,
        "failed_frames": 0 if p.returncode == 0 else 1,
        "notes": "pure TensorRT probe with --noDataTransfers; not video wall FPS",
        "trtexec_rc": p.returncode,
        "trtexec_log": str(log_path),
        "tegrastats_log": str(tegra_log),
        "tegrastats": parse_tegrastats(tegra_log),
    }


def flatten(row: dict) -> dict:
    tegra = row.get("tegrastats") or {}
    out = dict(row)
    out.pop("tegrastats", None)
    out["gr3d_avg"] = (tegra.get("gr3d") or {}).get("avg")
    out["gr3d_max"] = (tegra.get("gr3d") or {}).get("max")
    out["ram_avg_mb"] = (tegra.get("ram_used_mb") or {}).get("avg")
    out["ram_max_mb"] = (tegra.get("ram_used_mb") or {}).get("max")
    out["gpu_temp_avg_c"] = (tegra.get("gpu_temp_c") or {}).get("avg")
    out["gpu_temp_max_c"] = (tegra.get("gpu_temp_c") or {}).get("max")
    out["cpu_temp_avg_c"] = (tegra.get("cpu_temp_c") or {}).get("avg")
    out["cpu_temp_max_c"] = (tegra.get("cpu_temp_c") or {}).get("max")
    out["vdd_in_avg_mw"] = (tegra.get("vdd_in_mw") or {}).get("avg")
    out["vdd_in_max_mw"] = (tegra.get("vdd_in_mw") or {}).get("max")
    return out


def fmt(v, digits: int = 2) -> str:
    if v is None:
        return ""
    try:
        return f"{float(v):.{digits}f}"
    except Exception:
        return str(v)


def write_report(results: list[dict], env: dict) -> None:
    real = [r for r in results if r.get("input_mode") != "trtexec_raw_no_data_transfers" and r.get("wall_fps")]
    trt = [r for r in results if r.get("input_mode") == "trtexec_raw_no_data_transfers"]
    best = max(real, key=lambda r: r.get("wall_fps") or 0) if real else None

    lines = ["# Jetson Wall FPS Optimization Report\n\n"]
    lines.append("## Scope\n\n")
    lines.append("- Goal: increase video wall FPS for the fastest 640 TensorRT candidates without rerunning the full 48-combo matrix.\n")
    lines.append("- DeepStream was not installed. DLA/NVDLA was not used as the main execution path.\n")
    lines.append(f"- Video: `{VIDEO}` (`synthetic_stream_from_coco_val2017`, not a real camera stream).\n")
    lines.append("- All Ultralytics runs used TensorRT engines with `save=False`, `show=False`, `verbose=False`, `stream=True` where applicable, and did not access boxes/results per frame.\n\n")

    lines.append("## Environment\n\n```text\n")
    for k, v in env.items():
        lines.append(f"{k}: {v}\n")
    lines.append("```\n\n")

    if best:
        lines.append("## Conclusion\n\n")
        lines.append(f"- Highest measured video/Python wall FPS: `{best['input_mode']}` on `{best['model_name']}` `{best['precision']}` at `{fmt(best['wall_fps'])}` FPS.\n")
        base_same = next((r for r in real if r["model_name"] == best["model_name"] and r["precision"] == best["precision"] and r["input_mode"] == "baseline_ultralytics_video"), None)
        if base_same and base_same.get("wall_fps"):
            gain = (best["wall_fps"] / base_same["wall_fps"] - 1.0) * 100.0
            lines.append(f"- Gain over Ultralytics video baseline for the same engine: `{fmt(gain)}`%.\n")
        lines.append("- `predecoded_frame_ring` and `synthetic_numpy_frame_loop` estimate Python+Ultralytics+TensorRT upper bounds after removing decode/file IO. They are not end-to-end camera/video FPS.\n")
        lines.append("- GStreamer appsink uses Jetson hardware H.264 decode, but still copies frames into Python/CPU memory; this is not DeepStream zero-copy.\n\n")

    lines.append("## Results\n\n")
    lines.append("| Model | Precision | Input mode | Frames | Wall FPS | Mean wall ms | Mean read ms | Mean predict ms | GR3D avg/max | GPU temp max C | VDD_IN avg/max mW | Notes |\n")
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |\n")
    for row in sorted(results, key=lambda r: (r.get("input_mode") == "trtexec_raw_no_data_transfers", -(r.get("wall_fps") or 0))):
        tegra = row.get("tegrastats") or {}
        gr = tegra.get("gr3d") or {}
        gpu = tegra.get("gpu_temp_c") or {}
        pwr = tegra.get("vdd_in_mw") or {}
        lines.append(
            f"| {row.get('model_name')} | {row.get('precision')} | {row.get('input_mode')} | {row.get('frames_processed') or ''} | "
            f"{fmt(row.get('wall_fps'))} | {fmt(row.get('mean_wall_ms'))} | {fmt(row.get('mean_read_ms'))} | {fmt(row.get('mean_predict_ms'))} | "
            f"{fmt(gr.get('avg'))}/{fmt(gr.get('max'), 0)} | {fmt(gpu.get('max'))} | {fmt(pwr.get('avg'), 0)}/{fmt(pwr.get('max'), 0)} | {str(row.get('notes',''))[:140]} |\n"
        )

    lines.append("\n## Interpretation\n\n")
    modes = {}
    for row in real:
        modes.setdefault(row["input_mode"], []).append(row["wall_fps"])
    for mode, vals in sorted(modes.items(), key=lambda kv: statistics.fmean(kv[1]), reverse=True):
        lines.append(f"- `{mode}` average across tested engines: `{fmt(statistics.fmean(vals))}` FPS.\n")
    if trt:
        lines.append("- `trtexec_raw_no_data_transfers` is a pure TensorRT reference and should not be compared directly with video wall FPS.\n")
    lines.append("- Recommended deployment path: keep TensorRT engines, use a hardware-decoded pipeline, and move preprocessing/postprocessing out of Python when possible. For true zero-copy video analytics, a DeepStream or custom GStreamer/CUDA path would be the next step, but DeepStream was intentionally not installed in this run.\n\n")

    lines.append("## Output Files\n\n")
    lines.append(f"- CSV: `{CSV_PATH}`\n")
    lines.append(f"- JSON: `{JSON_PATH}`\n")
    lines.append(f"- JSONL: `{JSONL_PATH}`\n")
    lines.append(f"- logs: `{LOGS}`\n")
    lines.append(f"- tegrastats: `{TEGR}`\n")
    REPORT.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    ensure_dirs()
    env = {
        "generated_at": sh("date -Is")[1].strip(),
        "l4t": sh("cat /etc/nv_tegra_release 2>/dev/null || true")[1].strip(),
        "nvpmodel_before": sh("sudo -n nvpmodel -q --verbose 2>/dev/null || nvpmodel -q --verbose 2>/dev/null || true", timeout=20)[1].strip(),
        "jetson_clocks": sh("sudo -n jetson_clocks 2>&1 || true", timeout=30)[1].strip(),
        "opencv_gstreamer": "\n".join([ln for ln in cv2.getBuildInformation().splitlines() if "GStreamer" in ln]),
        "video_info": json.dumps(video_info(VIDEO), sort_keys=True),
        "gst_decoder": sh("gst-inspect-1.0 nvv4l2decoder >/dev/null 2>&1 && echo ok || echo missing")[1].strip(),
    }
    (LOGS / "environment.json").write_text(json.dumps(env, indent=2), encoding="utf-8")

    candidates = [
        ("yolo26n.pt", "int8"),
        ("yolo11n.pt", "int8"),
        ("yolo26n.pt", "fp16"),
    ]
    modes = [
        "baseline_ultralytics_video",
        "opencv_video_capture",
        "gstreamer_hwdecode_appsink",
        "predecoded_frame_ring",
        "synthetic_numpy_frame_loop",
    ]

    frame_ring = load_frame_ring(VIDEO, RING_FRAMES)
    results: list[dict] = []
    JSONL_PATH.write_text("", encoding="utf-8")

    for model_name, precision in candidates:
        engine_path, export_sec, engine_source = copy_or_build_engine(model_name, precision)
        for mode in modes:
            print(f"===== {model_name} {precision} {mode} =====", flush=True)
            try:
                row = run_experiment(model_name, precision, engine_path, mode, frame_ring)
                row["engine_export_sec_this_run"] = export_sec
                row["engine_source"] = engine_source
            except Exception as e:
                row = {
                    "model_name": model_name,
                    "precision": precision,
                    "engine_path": str(engine_path),
                    "input_path": str(VIDEO),
                    "input_mode": mode,
                    "video_resolution": "1280x720",
                    "target_imgsz": IMGSZ,
                    "warmup_sec": WARMUP_SEC,
                    "measure_sec": MEASURE_SEC,
                    "frames_processed": 0,
                    "wall_fps": None,
                    "failed_frames": 1,
                    "notes": f"FAILED: {e!r}",
                    "engine_export_sec_this_run": export_sec,
                    "engine_source": engine_source,
                }
            results.append(row)
            with JSONL_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
            JSON_PATH.write_text(json.dumps({"environment": env, "results": results}, indent=2, sort_keys=True), encoding="utf-8")
            rows = [flatten(r) for r in results]
            with CSV_PATH.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=sorted({k for row2 in rows for k in row2}))
                writer.writeheader()
                writer.writerows(rows)
            write_report(results, env)

        print(f"===== {model_name} {precision} trtexec probe =====", flush=True)
        row = run_trtexec_probe(model_name, precision, engine_path)
        results.append(row)
        with JSONL_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        JSON_PATH.write_text(json.dumps({"environment": env, "results": results}, indent=2, sort_keys=True), encoding="utf-8")
        rows = [flatten(r) for r in results]
        with CSV_PATH.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=sorted({k for row2 in rows for k in row2}))
            writer.writeheader()
            writer.writerows(rows)
        write_report(results, env)

    print(f"Wrote {REPORT}")
    print(f"Wrote {CSV_PATH}")
    print(f"Wrote {JSON_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
