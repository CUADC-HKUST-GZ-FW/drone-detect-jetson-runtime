#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from pathlib import Path


ROOT = Path.home() / "jetson_cascade_benchmark"

RUNS = [
    ("800+416 sequential", ROOT / "logs/cascade_800_416_seq_60s.json", ROOT / "tegrastats/cascade_800_416_seq_60s.log"),
    ("1024+416 sequential", ROOT / "logs/cascade_1024_416_seq_60s.json", ROOT / "tegrastats/cascade_1024_416_seq_60s.log"),
    ("800+416 pipeline_parse", ROOT / "logs/cascade_800_416_pipe_parse_60s.json", ROOT / "tegrastats/cascade_800_416_pipe_parse_60s.log"),
    ("1024+416 pipeline_parse", ROOT / "logs/cascade_1024_416_pipe_parse_60s.json", ROOT / "tegrastats/cascade_1024_416_pipe_parse_60s.log"),
]


def parse_json(path: Path) -> dict:
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError(f"no JSON in {path}")


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
        "ram": stat(vals(r"RAM\s+(\d+)/")),
    }


def meta(name: str) -> dict:
    p = ROOT / "logs" / f"{name}_metadata.json"
    return json.loads(p.read_text()) if p.exists() else {}


def main() -> None:
    rows = []
    for label, result_path, tegra_path in RUNS:
        result = parse_json(result_path)
        tegra = parse_tegra(tegra_path)
        row = {"label": label, **result}
        row.update(
            {
                "gr3d_avg": tegra["gr3d"]["avg"],
                "gr3d_max": tegra["gr3d"]["max"],
                "gpu_temp_avg": tegra["gpu_temp"]["avg"],
                "gpu_temp_max": tegra["gpu_temp"]["max"],
                "cpu_temp_avg": tegra["cpu_temp"]["avg"],
                "cpu_temp_max": tegra["cpu_temp"]["max"],
                "vdd_in_avg_w": (tegra["vdd_in"]["avg"] or 0) / 1000,
                "vdd_in_max_w": (tegra["vdd_in"]["max"] or 0) / 1000,
                "ram_avg_mb": tegra["ram"]["avg"],
                "ram_max_mb": tegra["ram"]["max"],
            }
        )
        rows.append(row)

    out_json = ROOT / "cascade_benchmark_results.json"
    out_csv = ROOT / "cascade_benchmark_results.csv"
    out_md = ROOT / "cascade_benchmark_report.md"
    out_json.write_text(json.dumps(rows, indent=2))

    keys = sorted({k for row in rows for k in row})
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)

    stage2_meta = meta("yolo26n_requested400_actual416_fp16")
    m800 = meta("yolo26n_800_fp16")
    m1024 = meta("yolo26n_1024_fp16")
    best_800 = max([r for r in rows if r["stage1_size"] == 800], key=lambda r: r["wall_fps"])
    best_1024 = max([r for r in rows if r["stage1_size"] == 1024], key=lambda r: r["wall_fps"])

    lines = []
    lines.append("# Cascaded YOLO C++ TensorRT Benchmark Report\n\n")
    lines.append("## Setup\n\n")
    lines.append("- Device: Jetson Orin NX Super, 40W mode, `jetson_clocks` locked.\n")
    lines.append("- Video: `~/jetson_benchmark_assets/videos/benchmark_5min_1080p30_coco_val2017_synthetic.mp4`.\n")
    lines.append("- Stage1 role: location only. The C++ runner ignores stage1 class and uses only the highest-confidence bbox as ROI.\n")
    lines.append("- Stage2 role: type decision. The C++ pipeline runner runs stage2 TensorRT and parses the top output class; type parsing is included in active latency.\n")
    lines.append("- Stage1 input is strict square via NVIDIA GStreamer pipeline and `nvcompositor`, with appsink/C++ receiving full square frames.\n")
    lines.append("- Precision: FP16 TensorRT for all engines; no INT8 used in these final runs.\n\n")
    lines.append("## Engine Sizes\n\n")
    lines.append(f"- Stage1 800 engine metadata: `imgsz={m800.get('imgsz')}`, `half={(m800.get('args') or {}).get('half')}`, `int8={(m800.get('args') or {}).get('int8')}`.\n")
    lines.append(f"- Stage1 1024 engine metadata: `imgsz={m1024.get('imgsz')}`, `half={(m1024.get('args') or {}).get('half')}`, `int8={(m1024.get('args') or {}).get('int8')}`.\n")
    lines.append(f"- Stage2 requested 400, actual engine metadata: `imgsz={stage2_meta.get('imgsz')}`, `half={(stage2_meta.get('args') or {}).get('half')}`, `int8={(stage2_meta.get('args') or {}).get('int8')}`.\n")
    lines.append("- Note: Ultralytics changed `imgsz=400` to `416` because YOLO max stride is 32. This is recorded as `stage2_requested_size=400`, `stage2_actual_size=416`.\n\n")

    lines.append("## Results\n\n")
    lines.append("| Run | FPS | Frames | Active mean ms | Active p90 ms | Read | S1 pre | S1 infer | ROI+S2 pre | S2 infer | Fallbacks | GR3D avg/max | GPU max | CPU max | VDD avg W |\n")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    for r in rows:
        lines.append(
            f"| {r['label']} | {r['wall_fps']:.2f} | {r['frames']} | {r['mean_active_ms']:.2f} | {r['p90_active_ms']:.2f} | "
            f"{r['mean_read_ms']:.2f} | {r['mean_stage1_pre_ms']:.2f} | {r['mean_stage1_infer_ms']:.2f} | "
            f"{r['mean_crop_stage2_pre_ms']:.2f} | {r['mean_stage2_infer_ms']:.2f} | {r['fallback_frames']} | "
            f"{r['gr3d_avg']:.1f}/{r['gr3d_max']:.0f} | {r['gpu_temp_max']:.2f} | {r['cpu_temp_max']:.2f} | {r['vdd_in_avg_w']:.2f} |\n"
        )

    lines.append("\n## Findings\n\n")
    lines.append(f"- Best 800+400-requested cascade result: `{best_800['label']}` at `{best_800['wall_fps']:.2f}` FPS.\n")
    lines.append(f"- Best 1024+400-requested cascade result: `{best_1024['label']}` at `{best_1024['wall_fps']:.2f}` FPS.\n")
    lines.append("- Pipeline parallelism improved both cascades by overlapping stage1 work with stage2 work across adjacent frames.\n")
    lines.append("- 1024+416 remains below 90 FPS in FP16 because concurrent stage1 and stage2 TensorRT execution competes for GPU resources: stage2 latency rises materially in the pipeline run.\n")
    lines.append("- The 800+416 cascade is already above 90 FPS; the 1024+416 cascade would likely require a lighter stage2 classifier, stage2 INT8, DLA/offload if supported, or lower stage2 frequency to exceed 90 without changing stage1 resolution.\n\n")

    lines.append("## Output Files\n\n")
    lines.append("- `~/jetson_cascade_benchmark/cascade_benchmark_report.md`\n")
    lines.append("- `~/jetson_cascade_benchmark/cascade_benchmark_results.csv`\n")
    lines.append("- `~/jetson_cascade_benchmark/cascade_benchmark_results.json`\n")
    lines.append("- `~/jetson_cascade_benchmark/scripts/cascade_trt_runner`\n")
    lines.append("- `~/jetson_cascade_benchmark/scripts/cascade_trt_pipeline_runner`\n")
    lines.append("- `~/jetson_cascade_benchmark/logs/`\n")
    lines.append("- `~/jetson_cascade_benchmark/tegrastats/`\n")
    out_md.write_text("".join(lines))
    print(out_md)
    print(f"best_800={best_800['wall_fps']:.2f}")
    print(f"best_1024={best_1024['wall_fps']:.2f}")


if __name__ == "__main__":
    main()
