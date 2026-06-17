#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from pathlib import Path


ROOT = Path.home() / "jetson_90fps_yolo26n800"


def parse_tegra(path: Path) -> dict:
    text = path.read_text(errors="replace") if path.exists() else ""

    def vals(pattern: str) -> list[float]:
        return [float(x) for x in re.findall(pattern, text)]

    def stat(xs: list[float]) -> dict:
        return {"avg": sum(xs) / len(xs), "max": max(xs)} if xs else {"avg": None, "max": None}

    return {
        "gr3d": stat(vals(r"GR3D_FREQ\s+(\d+)%")),
        "gpu_temp": stat(vals(r"gpu@([0-9.]+)C")),
        "cpu_temp": stat(vals(r"cpu@([0-9.]+)C")),
        "vdd_in": stat(vals(r"VDD_IN\s+(\d+)mW")),
        "ram_mb": stat(vals(r"RAM\s+(\d+)/")),
    }


def main() -> None:
    rows = []
    probe = json.loads((ROOT / "yolo26n800_realtime_probe.json").read_text())
    for r in probe:
        te = r.get("tegrastats", {}) or {}
        rows.append(
            {
                "mode": r.get("mode"),
                "fps": r.get("wall_fps"),
                "frames": r.get("frames"),
                "mean_ms": (r.get("wall_ms") or {}).get("mean"),
                "p90_ms": (r.get("wall_ms") or {}).get("p90"),
                "gpu_temp_max": (te.get("gpu_temp") or {}).get("max"),
                "cpu_temp_max": (te.get("cpu_temp") or {}).get("max"),
                "gr3d_avg": (te.get("gr3d") or {}).get("avg"),
                "gr3d_max": (te.get("gr3d") or {}).get("max"),
                "vdd_in_avg_mw": (te.get("vdd_in") or {}).get("avg"),
                "note": "raw TensorRT via trtexec"
                if str(r.get("mode", "")).startswith("trtexec")
                else "Ultralytics/Python path",
            }
        )

    native = []
    for line in (ROOT / "logs/native_trt_runner.jsonl").read_text().splitlines():
        line = line.strip()
        if line.startswith("{"):
            native.append(json.loads(line))

    native_tegra = parse_tegra(ROOT / "tegrastats/native_trt_800.log")
    for r in native:
        rows.append(
            {
                "mode": r.get("mode"),
                "fps": r.get("wall_fps"),
                "frames": r.get("frames"),
                "mean_ms": r.get("mean_ms"),
                "p90_ms": r.get("p90_ms"),
                "gpu_temp_max": native_tegra["gpu_temp"]["max"],
                "cpu_temp_max": native_tegra["cpu_temp"]["max"],
                "gr3d_avg": native_tegra["gr3d"]["avg"],
                "gr3d_max": native_tegra["gr3d"]["max"],
                "vdd_in_avg_mw": native_tegra["vdd_in"]["avg"],
                "note": "native C++ TensorRT runner; tegrastats covers both native modes",
            }
        )

    native_video_path = ROOT / "logs/native_trt_video_runner.json"
    if native_video_path.exists():
        native_video = None
        for line in native_video_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("{"):
                native_video = json.loads(line)
                break
        if native_video is None:
            raise RuntimeError(f"no JSON object found in {native_video_path}")
        native_video_tegra = parse_tegra(ROOT / "tegrastats/native_trt_video_800.log")
        rows.append(
            {
                "mode": native_video.get("mode"),
                "fps": native_video.get("wall_fps"),
                "frames": native_video.get("frames"),
                "mean_ms": native_video.get("mean_wall_ms"),
                "p90_ms": native_video.get("p90_wall_ms"),
                "gpu_temp_max": native_video_tegra["gpu_temp"]["max"],
                "cpu_temp_max": native_video_tegra["cpu_temp"]["max"],
                "gr3d_avg": native_video_tegra["gr3d"]["avg"],
                "gr3d_max": native_video_tegra["gr3d"]["max"],
                "vdd_in_avg_mw": native_video_tegra["vdd_in"]["avg"],
                "note": (
                    "native C++ GStreamer hwdecode + CPU letterbox/normalize + TensorRT; "
                    f"read {native_video.get('mean_read_ms'):.2f} ms, preprocess {native_video.get('mean_preprocess_ms'):.2f} ms, infer/copy {native_video.get('mean_infer_copy_ms'):.2f} ms"
                ),
            }
        )
    else:
        native_video_tegra = {"gpu_temp": {"max": None}, "cpu_temp": {"max": None}, "vdd_in": {"avg": None}}

    out_json = ROOT / "yolo26n800_optimization_summary.json"
    out_csv = ROOT / "yolo26n800_optimization_summary.csv"
    out_md = ROOT / "yolo26n800_optimization_summary.md"
    out_json.write_text(json.dumps(rows, indent=2))

    keys = [
        "mode",
        "fps",
        "frames",
        "mean_ms",
        "p90_ms",
        "gpu_temp_max",
        "cpu_temp_max",
        "gr3d_avg",
        "gr3d_max",
        "vdd_in_avg_mw",
        "note",
    ]
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)

    best = max([r for r in rows if r.get("fps")], key=lambda x: x["fps"])
    best_real = max(
        [
            r
            for r in rows
            if r.get("fps") and r["mode"] in ["ultralytics_video_800", "opencv_videocapture_800", "gstreamer_hwdecode_800"]
        ],
        key=lambda x: x["fps"],
    )
    best_py = max(
        [r for r in rows if r.get("fps") and r["mode"] in ["predecoded_ring_800", "synthetic_numpy_800"]],
        key=lambda x: x["fps"],
    )
    best_native = max(
        [r for r in rows if r.get("fps") and str(r["mode"]).startswith("native_trt")],
        key=lambda x: x["fps"],
    )
    best_end_to_end = max(
        [
            r
            for r in rows
            if r.get("fps")
            and r["mode"]
            in [
                "ultralytics_video_800",
                "opencv_videocapture_800",
                "gstreamer_hwdecode_800",
                "native_cpp_gstreamer_preprocess_trt",
            ]
        ],
        key=lambda x: x["fps"],
    )
    h2d_d2h = [r for r in rows if r["mode"] == "native_trt_h2d_d2h"][0]

    lines = []
    lines.append("# YOLO26n 800 Wall FPS Optimization Summary\n\n")
    lines.append("## Setup\n\n")
    lines.append("- Device: Jetson Orin NX Super, power mode 40W, `jetson_clocks` locked CPU/GPU/EMC.\n")
    lines.append("- Engine: `~/jetson_90fps_yolo26n800/engines/yolo26n_800_fp16.engine`; raw plan: `yolo26n_800_fp16.raw.engine`.\n")
    lines.append("- Input video: `~/jetson_benchmark_assets/videos/benchmark_5min_720p30_coco_val2017_synthetic.mp4`.\n")
    lines.append("- Python paths: 5s warmup, 60s measured. Native C++ paths: 5s warmup, 60s measured per mode.\n")
    lines.append("- Temperature and power were collected with `tegrastats`; native raw tegrastats file covers both raw native modes.\n\n")

    lines.append("## Results\n\n")
    lines.append("| Mode | FPS | Frames | Mean ms | P90 ms | GR3D avg/max | GPU temp max | CPU temp max | VDD_IN avg W | Note |\n")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |\n")
    for r in sorted(rows, key=lambda x: (x.get("fps") or 0), reverse=True):
        lines.append(
            f"| {r['mode']} | {(r.get('fps') or 0):.2f} | {r.get('frames') or ''} | "
            f"{(r.get('mean_ms') or 0):.2f} | {(r.get('p90_ms') or 0):.2f} | "
            f"{(r.get('gr3d_avg') or 0):.1f}/{(r.get('gr3d_max') or 0):.0f} | "
            f"{(r.get('gpu_temp_max') or 0):.2f} | {(r.get('cpu_temp_max') or 0):.2f} | "
            f"{((r.get('vdd_in_avg_mw') or 0) / 1000):.2f} | {r.get('note', '')} |\n"
        )

    lines.append("\n## Findings\n\n")
    lines.append(
        f"- Fastest measured end-to-end video path was `{best_end_to_end['mode']}` at `{best_end_to_end['fps']:.2f}` FPS. "
        "This path uses GStreamer/NVIDIA H.264 decode into C++ OpenCV, CPU letterbox/normalize, then direct TensorRT enqueue, avoiding Ultralytics runtime overhead.\n"
    )
    lines.append(
        f"- Highest actual video ingest path through Ultralytics/OpenCV was `{best_real['mode']}` at `{best_real['fps']:.2f}` FPS. "
        "Hardware H.264 decode via GStreamer raised 800px wall FPS versus Ultralytics video input, but still stayed below 90 FPS because frames return to Python/CPU through appsink and then enter Ultralytics preprocessing/postprocess.\n"
    )
    lines.append(
        f"- Removing decode by using predecoded/synthetic frames only reached `{best_py['fps']:.2f}` FPS, so decode is not the dominant remaining bottleneck. "
        "The dominant cost is the Ultralytics Python predict path, including preprocessing, result construction, and postprocess handling.\n"
    )
    lines.append(
        f"- Native TensorRT C++ runner reached `{best_native['fps']:.2f}` FPS. The H2D+D2H mode reached `{h2d_d2h['fps']:.2f}` FPS, which clears the 90 FPS target for an already-preprocessed tensor stream.\n"
    )
    lines.append("- Raw TensorRT via `trtexec` remains around 197 FPS with transfers, consistent with the native runner.\n")
    lines.append(
        f"- Thermal headroom was acceptable in this run: Python/GStreamer path GPU max was `{best_real['gpu_temp_max']:.2f}C`; "
        f"native TensorRT combined run GPU max was `{native_tegra['gpu_temp']['max']:.2f}C`, CPU max `{native_tegra['cpu_temp']['max']:.2f}C`, "
        f"VDD_IN avg `{native_tegra['vdd_in']['avg'] / 1000:.2f}W`; native C++ video path GPU max was `{best_end_to_end['gpu_temp_max']:.2f}C`, "
        f"CPU max `{best_end_to_end['cpu_temp_max']:.2f}C`, VDD_IN avg `{best_end_to_end['vdd_in_avg_mw'] / 1000:.2f}W`.\n"
    )

    lines.append("\n## Recommendation\n\n")
    lines.append(
        "For >90 FPS at 800px, stop using Ultralytics `predict()` as the runtime loop. The tested C++ GStreamer + TensorRT path already clears 90 FPS. The next production hardening step is to replace CPU letterbox/normalize with CUDA/NVMM preprocessing and keep decode/preprocess/inference buffers closer to GPU memory for more headroom and lower CPU load.\n"
    )

    lines.append("\n## Output Files\n\n")
    lines.append("- `~/jetson_90fps_yolo26n800/yolo26n800_realtime_probe.md`\n")
    lines.append("- `~/jetson_90fps_yolo26n800/yolo26n800_optimization_summary.md`\n")
    lines.append("- `~/jetson_90fps_yolo26n800/yolo26n800_optimization_summary.csv`\n")
    lines.append("- `~/jetson_90fps_yolo26n800/yolo26n800_optimization_summary.json`\n")
    lines.append("- `~/jetson_90fps_yolo26n800/logs/native_trt_runner.jsonl`\n")
    lines.append("- `~/jetson_90fps_yolo26n800/logs/native_trt_video_runner.json`\n")
    lines.append("- `~/jetson_90fps_yolo26n800/tegrastats/`\n")

    out_md.write_text("".join(lines))
    print(out_md)
    print(f"best={best['mode']} {best['fps']:.2f}")
    print(f"best_real={best_real['mode']} {best_real['fps']:.2f}")
    print(f"best_end_to_end={best_end_to_end['mode']} {best_end_to_end['fps']:.2f}")
    print(f"best_native={best_native['mode']} {best_native['fps']:.2f}")


if __name__ == "__main__":
    main()
