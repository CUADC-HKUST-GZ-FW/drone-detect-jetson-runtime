#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


root = Path.home() / "jetson_wallfps_optimization"
report = root / "wallfps_optimization_report.md"
data = json.loads((root / "wallfps_results.json").read_text())
rows = data["results"]

actual_video = [
    r
    for r in rows
    if r.get("input_mode")
    not in ("trtexec_raw_no_data_transfers", "synthetic_numpy_frame_loop", "predecoded_frame_ring")
    and r.get("wall_fps")
]
int8_actual = [r for r in actual_video if r.get("precision") == "int8"]
synthetic = [r for r in rows if r.get("input_mode") == "synthetic_numpy_frame_loop" and r.get("wall_fps")]
predecoded = [r for r in rows if r.get("input_mode") == "predecoded_frame_ring" and r.get("wall_fps")]

best_actual = max(actual_video, key=lambda r: r["wall_fps"])
best_int8 = max(int8_actual, key=lambda r: r["wall_fps"])
best_syn = max(synthetic, key=lambda r: r["wall_fps"])
best_pre = max(predecoded, key=lambda r: r["wall_fps"])

lines = ["\n## Final Summary\n\n"]
lines.append(
    f"- Best actual video-ingest path: `{best_actual.get('model_name')}` `{best_actual.get('precision')}` "
    f"via `{best_actual.get('input_mode')}` at `{best_actual.get('wall_fps'):.2f}` FPS.\n"
)
lines.append(
    f"- Best INT8 actual video-ingest path: `{best_int8.get('model_name')}` "
    f"via `{best_int8.get('input_mode')}` at `{best_int8.get('wall_fps'):.2f}` FPS.\n"
)
lines.append(
    f"- Best decode-free predecoded-frame estimate: `{best_pre.get('model_name')}` `{best_pre.get('precision')}` "
    f"at `{best_pre.get('wall_fps'):.2f}` FPS.\n"
)
lines.append(
    f"- Best synthetic no-decode upper-bound estimate: `{best_syn.get('model_name')}` `{best_syn.get('precision')}` "
    f"at `{best_syn.get('wall_fps'):.2f}` FPS.\n"
)

lines.append("\n### GStreamer Hardware Decode Gain\n\n")
for model, precision in sorted({(r["model_name"], r["precision"]) for r in actual_video}):
    base = next(
        r
        for r in rows
        if r.get("model_name") == model
        and r.get("precision") == precision
        and r.get("input_mode") == "baseline_ultralytics_video"
    )
    gst = next(
        r
        for r in rows
        if r.get("model_name") == model
        and r.get("precision") == precision
        and r.get("input_mode") == "gstreamer_hwdecode_appsink"
    )
    cv = next(
        r
        for r in rows
        if r.get("model_name") == model
        and r.get("precision") == precision
        and r.get("input_mode") == "opencv_video_capture"
    )
    gain = (gst["wall_fps"] / base["wall_fps"] - 1.0) * 100.0
    lines.append(
        f"- `{model}` `{precision}`: GStreamer `{gst['wall_fps']:.2f}` FPS vs baseline "
        f"`{base['wall_fps']:.2f}` FPS = `{gain:+.1f}%`; OpenCV baseline `{cv['wall_fps']:.2f}` FPS.\n"
    )

lines.append("\n### Bottleneck Assessment\n\n")
lines.append(
    "- Hardware H.264 decode through `nvv4l2decoder + nvvidconv + appsink` is the best real video path tested, "
    "improving wall FPS by roughly 16-19% over direct Ultralytics video reading.\n"
)
lines.append(
    "- Plain OpenCV `VideoCapture` does not improve wall FPS; read time is about 4.4-5.0 ms/frame, "
    "which cancels out any benefit.\n"
)
lines.append(
    "- Predecoded and synthetic loops show the Python + Ultralytics + TensorRT + postprocess ceiling is around "
    "45-51 FPS for these 640 engines. After decode is improved, the next bottleneck is Python/Ultralytics "
    "per-frame preprocessing/postprocessing/result-object overhead rather than TensorRT engine execution alone.\n"
)
lines.append(
    "- Recommended next deployment path: keep TensorRT engines, use Jetson hardware decode, and move frame conversion, "
    "preprocess, and postprocess into a native GStreamer/CUDA or DeepStream-style zero-copy pipeline. DeepStream was "
    "intentionally not installed in this run.\n"
)

text = report.read_text()
marker = "\n## Final Summary\n"
if marker in text:
    text = text.split(marker)[0].rstrip() + "\n"
report.write_text(text + "".join(lines), encoding="utf-8")
print(report)
