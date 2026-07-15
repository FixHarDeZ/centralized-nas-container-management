"""Build-time script: fetch BGE-M3 ONNX export and quantize to int8.

Runs inside `docker build`. Downloads the community ONNX export of BAAI/bge-m3
(includes dense + sparse + colbert heads as graph outputs), then applies
dynamic int8 weight quantization (~2.2GB fp32 -> ~600MB int8) and deletes the
fp32 copy to keep the image small.
"""

import os
import shutil
import sys

from huggingface_hub import snapshot_download
from onnxruntime.quantization import QuantType, quantize_dynamic

SRC_REPO = os.getenv("ONNX_SRC_REPO", "aapot/bge-m3-onnx")
OUT_PATH = os.getenv("ONNX_MODEL_PATH", "/models/bge-m3-int8.onnx")


def main() -> int:
    src_dir = snapshot_download(SRC_REPO)
    fp32 = os.path.join(src_dir, "model.onnx")
    if not os.path.exists(fp32):
        # some exports name it differently
        candidates = [f for f in os.listdir(src_dir) if f.endswith(".onnx")]
        if not candidates:
            print(f"no .onnx file found in {src_dir}", file=sys.stderr)
            return 1
        fp32 = os.path.join(src_dir, candidates[0])

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    print(f"quantizing {fp32} -> {OUT_PATH}")
    quantize_dynamic(
        model_input=fp32,
        model_output=OUT_PATH,
        weight_type=QuantType.QInt8,
        use_external_data_format=False,
    )
    # free build-layer space: drop the fp32 snapshot
    shutil.rmtree(src_dir, ignore_errors=True)
    size_mb = os.path.getsize(OUT_PATH) / 1e6
    print(f"done: {OUT_PATH} ({size_mb:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
