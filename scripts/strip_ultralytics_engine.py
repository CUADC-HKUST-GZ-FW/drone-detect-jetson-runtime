#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def split_ultralytics_engine(data: bytes) -> tuple[dict[str, Any] | None, bytes]:
    if len(data) < 8:
        return None, data
    meta_len = int.from_bytes(data[:4], byteorder="little", signed=False)
    if meta_len <= 0 or meta_len > min(16 * 1024 * 1024, len(data) - 4):
        return None, data
    meta_blob = data[4 : 4 + meta_len]
    try:
        metadata = json.loads(meta_blob.decode("utf-8"))
    except Exception:
        return None, data
    if not isinstance(metadata, dict):
        return None, data
    return metadata, data[4 + meta_len :]


def verify_with_tensorrt(raw: bytes) -> None:
    import tensorrt as trt

    logger = trt.Logger(trt.Logger.WARNING)
    runtime = trt.Runtime(logger)
    engine = runtime.deserialize_cuda_engine(raw)
    if engine is None:
        raise RuntimeError("TensorRT failed to deserialize raw engine")


def main() -> int:
    parser = argparse.ArgumentParser(description="Strip Ultralytics metadata prefix from a TensorRT engine.")
    parser.add_argument("engine")
    parser.add_argument("--output", default=None)
    parser.add_argument("--metadata-output", default=None)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    engine_path = Path(args.engine)
    output = Path(args.output or engine_path.with_suffix(".raw.engine"))
    metadata_output = Path(args.metadata_output) if args.metadata_output else output.with_suffix(".metadata.json")

    data = engine_path.read_bytes()
    metadata, raw = split_ultralytics_engine(data)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)
    if metadata is not None:
        metadata_output.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.verify:
        verify_with_tensorrt(raw)
    print(json.dumps({
        "input": str(engine_path),
        "output": str(output),
        "metadata_output": str(metadata_output) if metadata is not None else None,
        "input_bytes": len(data),
        "raw_bytes": len(raw),
        "metadata_stripped": metadata is not None,
        "verified": bool(args.verify),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
