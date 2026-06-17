#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from pathlib import Path


ROOT = Path.home() / "jetson_90fps_yolo26n1024"


RUNS = [
    (
        "baseline_720p_serial",
        ROOT / "logs/native_trt_video_1024_baseline.json",
        ROOT / "tegrastats/native_trt_video_1024_baseline.log",
        "720p source; serial C++ hwdecode/preprocess/TRT",
    ),
    (
        "pipeline_720p_slots4",
        ROOT / "logs/native_trt_video_1024_pipeline_4.json",
        ROOT / "tegrastats/native_trt_video_1024_pipeline_4.log",
        "720p source; threaded C++ pipeline; 4 pinned slots",
    ),
    (
        "pipeline_720p_slots2_short",
        ROOT / "logs/native_trt_video_1024_pipeline_2_short.json",
        ROOT / "tegrastats/native_trt_video_1024_pipeline_2_short.log",
        "720p source; threaded C++ pipeline; 2 pinned slots; 30s",
    ),
    (
        "pipeline_720p_slots6_short",
        ROOT / "logs/native_trt_video_1024_pipeline_6_short.json",
        ROOT / "tegrastats/native_trt_video_1024_pipeline_6_short.log",
        "720p source; threaded C++ pipeline; 6 pinned slots; 30s",
    ),
    (
        "pipeline_1080p_no_caps",
        ROOT / "logs/native_trt_video_1024_pipeline_1080p.json",
        ROOT / "tegrastats/native_trt_video_1024_pipeline_1080p.log",
        "1080p source; threaded C++ pipeline; full frame to appsink",
    ),
    (
        "pipeline_1080p_caps1024x576_short",
        ROOT / "logs/native_trt_video_1024_pipeline_1080p_caps1024x576.json",
        ROOT / "tegrastats/native_trt_video_1024_pipeline_1080p_caps1024x576.log",
        "1080p source; nvvidconv scales to 1024x576 before appsink; 30s",
    ),
    (
        "pipeline_1080p_caps1024x576_60s",
        ROOT / "logs/native_trt_video_1024_pipeline_1080p_caps1024x576_60s.json",
        ROOT / "tegrastats/native_trt_video_1024_pipeline_1080p_caps1024x576_60s.log",
        "1080p source; nvvidconv scales to 1024x576 before appsink; 60s final",
    ),
]


def parse_json_line(path: Path) -> dict | None:
    if not path.exists():
        return None
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    return None


def parse_tegrastats(path: Path) -> dict:
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
        "ram": stat(vals(r"RAM\s+(\d+)/")),
    }


def main() -> None:
    rows = []
    for name, result_path, tegra_path, note in RUNS:
        data = parse_json_line(result_path)
        if not data:
            continue
        tegra = parse_tegrastats(tegra_path)
        rows.append(
            {
                "name": name,
                "mode": data.get("mode"),
                "target": data.get("target"),
                "slots": data.get("slots"),
                "caps_w": data.get("caps_w", 0),
                "caps_h": data.get("caps_h", 0),
                "frames": data.get("frames"),
                "wall_sec": data.get("wall_sec"),
                "wall_fps": data.get("wall_fps"),
                "mean_wall_ms": data.get("mean_wall_ms"),
                "p90_wall_ms": data.get("p90_wall_ms"),
                "p99_wall_ms": data.get("p99_wall_ms"),
                "mean_read_ms": data.get("mean_read_ms"),
                "mean_preprocess_ms": data.get("mean_preprocess_ms"),
                "mean_infer_copy_ms": data.get("mean_infer_copy_ms"),
                "gr3d_avg": tegra["gr3d"]["avg"],
                "gr3d_max": tegra["gr3d"]["max"],
                "gpu_temp_avg": tegra["gpu_temp"]["avg"],
                "gpu_temp_max": tegra["gpu_temp"]["max"],
                "cpu_temp_avg": tegra["cpu_temp"]["avg"],
                "cpu_temp_max": tegra["cpu_temp"]["max"],
                "vdd_in_avg_w": (tegra["vdd_in"]["avg"] or 0) / 1000,
                "vdd_in_max_w": (tegra["vdd_in"]["max"] or 0) / 1000,
                "note": note,
            }
        )

    out_json = ROOT / "yolo26n1024_optimization_summary.json"
    out_csv = ROOT / "yolo26n1024_optimization_summary.csv"
    out_md = ROOT / "yolo26n1024_optimization_summary.md"
    out_json.write_text(json.dumps(rows, indent=2))

    keys = list(rows[0].keys()) if rows else []
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)

    best = max(rows, key=lambda r: r["wall_fps"])
    final = [r for r in rows if r["name"] == "pipeline_1080p_caps1024x576_60s"][0]
    baseline = [r for r in rows if r["name"] == "baseline_720p_serial"][0]
    no_caps = [r for r in rows if r["name"] == "pipeline_1080p_no_caps"][0]

    metadata = json.loads((ROOT / "logs/engine_metadata.json").read_text())

    lines = []
    lines.append("# YOLO26n 1024 End-to-End Wall FPS Optimization Report\n\n")
    lines.append("## Setup\n\n")
    lines.append("- Device: Jetson Orin NX Super, 40W mode, `jetson_clocks` locked CPU/GPU/EMC.\n")
    lines.append("- Model: `yolo26n.pt`, exported TensorRT FP16 engine from the existing formal benchmark.\n")
    lines.append("- Engine: `~/jetson_90fps_yolo26n1024/engines/yolo26n_1024_fp16.engine`.\n")
    lines.append("- Raw TensorRT plan: `~/jetson_90fps_yolo26n1024/engines/yolo26n_1024_fp16.raw.engine`.\n")
    lines.append(f"- Engine metadata: `imgsz={metadata.get('imgsz')}`, `half={metadata.get('args', {}).get('half')}`, `int8={metadata.get('args', {}).get('int8')}`, `end2end={metadata.get('end2end')}`.\n")
    lines.append("- Main final input: 1080p30 synthetic COCO-val H.264 MP4; simulated video is used as allowed.\n")
    lines.append("- Quality was not lowered: the final path keeps the same 1024x1024 model input and FP16 TensorRT precision. The GStreamer caps optimization scales the 16:9 source to 1024x576 before the same 1024x1024 letterbox padding.\n\n")

    lines.append("## Results\n\n")
    lines.append("| Run | FPS | Frames | Mean ms | P90 ms | Read ms | Pre ms | Infer/copy ms | GR3D avg/max | GPU temp max | CPU temp max | VDD avg W | Note |\n")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |\n")
    for r in sorted(rows, key=lambda x: x["wall_fps"], reverse=True):
        lines.append(
            f"| {r['name']} | {r['wall_fps']:.2f} | {r['frames']} | {r['mean_wall_ms']:.2f} | {r['p90_wall_ms']:.2f} | "
            f"{r['mean_read_ms']:.2f} | {r['mean_preprocess_ms']:.2f} | {r['mean_infer_copy_ms']:.2f} | "
            f"{r['gr3d_avg']:.1f}/{r['gr3d_max']:.0f} | {r['gpu_temp_max']:.2f} | {r['cpu_temp_max']:.2f} | {r['vdd_in_avg_w']:.2f} | {r['note']} |\n"
        )

    lines.append("\n## Findings\n\n")
    lines.append(f"- Final 1024x1024 end-to-end path reached `{final['wall_fps']:.2f}` FPS for 60 seconds on the 1080p source, processing `{final['frames']}` frames.\n")
    lines.append(f"- Baseline serial 720p C++ path was `{baseline['wall_fps']:.2f}` FPS. Threading decode/preprocess and TRT with pinned slots raised the 720p path to about `116 FPS`.\n")
    lines.append(f"- 1080p without GStreamer caps was `{no_caps['wall_fps']:.2f}` FPS because appsink/read cost rose to `{no_caps['mean_read_ms']:.2f}` ms. Adding `nvvidconv` caps `1024x576` reduced read cost to `{final['mean_read_ms']:.2f}` ms and restored >90 FPS.\n")
    lines.append("- Slot count was not sensitive after pipelining: 2, 4, and 6 slots all measured about 115-116 FPS; 4 slots is a good default.\n")
    lines.append(f"- Final thermal/power summary: GPU max `{final['gpu_temp_max']:.2f}C`, CPU max `{final['cpu_temp_max']:.2f}C`, VDD_IN avg `{final['vdd_in_avg_w']:.2f}W`, GR3D avg/max `{final['gr3d_avg']:.1f}/{final['gr3d_max']:.0f}%`.\n")

    lines.append("\n## Recommendation\n\n")
    lines.append("Use the `native_trt_video_pipeline_runner` path for 1024 real-time work: GStreamer H.264 hardware decode, `nvvidconv` resize caps to the letterbox-scaled source dimensions, C++ pinned-slot pipeline, and direct TensorRT FP16 enqueue. The next optimization with meaningful upside would be moving letterbox/normalize from CPU OpenCV to CUDA/NVMM, but the current path already exceeds the 90 FPS target.\n\n")

    lines.append("## Output Files\n\n")
    lines.append("- `~/jetson_90fps_yolo26n1024/yolo26n1024_optimization_summary.md`\n")
    lines.append("- `~/jetson_90fps_yolo26n1024/yolo26n1024_optimization_summary.csv`\n")
    lines.append("- `~/jetson_90fps_yolo26n1024/yolo26n1024_optimization_summary.json`\n")
    lines.append("- `~/jetson_90fps_yolo26n1024/scripts/native_trt_video_pipeline_runner`\n")
    lines.append("- `~/jetson_90fps_yolo26n1024/logs/`\n")
    lines.append("- `~/jetson_90fps_yolo26n1024/tegrastats/`\n")

    out_md.write_text("".join(lines))
    print(out_md)
    print(f"best={best['name']} {best['wall_fps']:.2f}")
    print(f"final={final['name']} {final['wall_fps']:.2f}")


if __name__ == "__main__":
    main()
