"""BGE-M3 encoders: ONNX int8 (fast, CPU) with FlagEmbedding torch fallback.

Both backends expose the same subset of the FlagEmbedding API used by main.py:

    out = encoder.encode(texts, return_dense=True, return_sparse=True)
    out["dense_vecs"]       -> ndarray [batch, 1024]
    out["lexical_weights"]  -> list[dict[token_id, weight]]
"""

import logging
import os

log = logging.getLogger(__name__)

ONNX_MODEL_PATH = os.getenv("ONNX_MODEL_PATH", "/models/bge-m3-int8.onnx")


class OnnxBGEM3Encoder:
    """int8-quantized BGE-M3 (dense + sparse heads) via onnxruntime."""

    def __init__(self, model_path: str = ONNX_MODEL_PATH, threads: int | None = None):
        import onnxruntime as ort
        from transformers import AutoTokenizer

        if threads is None:
            threads = int(os.getenv("OMP_NUM_THREADS", "4"))

        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            model_path, sess_options=so, providers=["CPUExecutionProvider"]
        )
        self.tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-m3")
        self.special_ids = set(self.tokenizer.all_special_ids)
        self._input_names = {i.name for i in self.session.get_inputs()}
        log.info(
            "ONNX BGE-M3 loaded: %s (threads=%d, outputs=%s)",
            model_path,
            threads,
            [o.name for o in self.session.get_outputs()],
        )

    def encode(self, texts: list[str], **_kw) -> dict:
        enc = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=8192,
            return_tensors="np",
        )
        feed = {k: v for k, v in enc.items() if k in self._input_names}
        dense, sparse = self.session.run(["dense_vecs", "sparse_vecs"], feed)

        lexical_weights = []
        for i in range(len(texts)):
            weights: dict[int, float] = {}
            token_ids = enc["input_ids"][i]
            mask = enc["attention_mask"][i]
            token_w = sparse[i].reshape(-1)
            for tid, w, m in zip(token_ids, token_w, mask):
                if not m:
                    continue
                tid = int(tid)
                if tid in self.special_ids:
                    continue
                w = float(w)
                if w > weights.get(tid, 0.0):
                    weights[tid] = w
            lexical_weights.append(weights)

        return {"dense_vecs": dense, "lexical_weights": lexical_weights}


def load_encoder():
    """Load encoder per EMBEDDING_BACKEND (onnx|torch), falling back to torch."""
    backend = os.getenv("EMBEDDING_BACKEND", "onnx").lower()
    if backend == "onnx":
        try:
            return OnnxBGEM3Encoder(), "onnx-int8"
        except Exception as exc:  # missing model file, bad export, etc.
            log.warning("ONNX encoder unavailable (%s); falling back to torch", exc)
    from FlagEmbedding import BGEM3FlagModel

    return BGEM3FlagModel("BAAI/bge-m3"), "torch"
