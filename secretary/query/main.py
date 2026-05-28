import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

import cohere
from fastapi import FastAPI
from FlagEmbedding import BGEM3FlagModel
from pydantic import BaseModel
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Fusion,
    FusionQuery,
    Prefetch,
    SparseVector,
)

import llm_client
import nous_auth
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "secretary_notes")
COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")
COHERE_RERANK_MODEL = os.getenv("COHERE_RERANK_MODEL", "rerank-multilingual-v3.0")

qdrant: AsyncQdrantClient | None = None

SYSTEM_PROMPT = """You are a personal secretary assistant for the user.
Answer based ONLY on the numbered context blocks provided.
Rules:
- Respond in the SAME LANGUAGE as the question (Thai or English)
- Use ONLY the provided context, no outside knowledge
- If context is insufficient, say:
    Thai: "ไม่พบข้อมูลในบันทึก ลองเพิ่มหัวข้อ: <suggested topic>"
    English: "Not found in notes. Consider adding: <suggested topic>"
- Cite sources inline with [1] [2] [3]
- Be concise, use bullet points for lists
- If ambiguous, ask ONE clarifying question"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global qdrant
    provider = os.getenv("LLM_PROVIDER", "anthropic")
    log.info("Loading BGEM3FlagModel (BAAI/bge-m3)…")
    app.state.model = BGEM3FlagModel("BAAI/bge-m3")
    log.info("BGE-M3 loaded")
    log.info("LLM provider: %s | model: %s", provider, _active_model_name(provider))
    qdrant = AsyncQdrantClient(url=QDRANT_URL)
    yield
    await qdrant.close()


def _active_model_name(provider: str) -> str:
    mapping = {
        "anthropic": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        "openrouter": os.getenv("OPENROUTER_MODEL", ""),
        "nous": os.getenv("NOUS_MODEL", "Hermes-4-70B"),
    }
    return mapping.get(provider, "unknown")


app = FastAPI(title="secretary-query", lifespan=lifespan)


class QueryRequest(BaseModel):
    question: str
    top_k_retrieve: int = 20
    top_k_final: int = 3
    session_id: str = ""


@app.post("/query")
async def query(req: QueryRequest):
    t0 = time.monotonic()

    model: BGEM3FlagModel = app.state.model

    # Encode runs on CPU — run in thread to avoid blocking the event loop
    out = await asyncio.to_thread(
        model.encode,
        [req.question],
        return_dense=True,
        return_sparse=True,
    )

    dense_vec = out["dense_vecs"][0].tolist()

    lw = out["lexical_weights"][0]
    sparse_indices = [int(k) for k in lw.keys()]
    sparse_values = [float(v) for v in lw.values()]
    sparse_vec = SparseVector(indices=sparse_indices, values=sparse_values)

    results = await qdrant.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            Prefetch(query=dense_vec, using="dense", limit=req.top_k_retrieve),
            Prefetch(query=sparse_vec, using="sparse", limit=req.top_k_retrieve),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=req.top_k_retrieve,
        with_payload=True,
    )

    hits = results.points

    retrieval_method = "hybrid"
    if COHERE_API_KEY:
        co = cohere.AsyncClientV2(api_key=COHERE_API_KEY)
        docs = [h.payload.get("text", "") for h in hits]
        rerank_resp = await co.rerank(
            model=COHERE_RERANK_MODEL,
            query=req.question,
            documents=docs,
            top_n=req.top_k_final,
        )
        hits = [
            hits[r.index].model_copy(update={"score": r.relevance_score})
            for r in rerank_resp.results
        ]
        retrieval_method = "hybrid+rerank"
    else:
        hits = hits[: req.top_k_final]

    context_blocks = []
    for i, h in enumerate(hits, start=1):
        breadcrumb = h.payload.get("breadcrumb", "")
        text = h.payload.get("text", "")
        context_blocks.append(f"[{i}] {breadcrumb}\n{text}")

    context_str = "\n\n".join(context_blocks)
    user_msg = f"# Context\n{context_str}\n\n# Question\n{req.question}"

    try:
        answer = await llm_client.get_llm_response(SYSTEM_PROMPT, user_msg)
    except Exception as exc:
        log.error("LLM call failed: %s", exc)
        return JSONResponse(status_code=502, content={"error": str(exc)})

    sources = [
        {
            "breadcrumb": h.payload.get("breadcrumb", ""),
            "page_url": h.payload.get("page_url", ""),
            "score": float(h.score),
        }
        for h in hits
    ]

    latency_ms = int((time.monotonic() - t0) * 1000)
    return {
        "answer": answer,
        "sources": sources,
        "retrieval_method": retrieval_method,
        "latency_ms": latency_ms,
    }


@app.get("/health")
async def health():
    try:
        info = await qdrant.get_collection(COLLECTION_NAME)
        return {
            "status": "ok",
            "qdrant_ok": True,
            "collection_stats": {"points_count": info.points_count},
        }
    except Exception:
        return {
            "status": "error",
            "qdrant_ok": False,
            "collection_stats": {"points_count": 0},
        }


@app.post("/ingest-trigger")
async def ingest_trigger():
    try:
        proc = await asyncio.create_subprocess_exec(
            "python",
            "/ingest/ingest.py",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        combined = (stdout + stderr).decode(errors="replace")
        if proc.returncode == 0:
            return {"status": "done", "summary": combined}
        return {"status": "error", "summary": combined}
    except Exception as exc:
        return {"status": "error", "summary": str(exc)}


@app.get("/nous/auth")
async def nous_auth_start():
    return await nous_auth.token_manager.start_device_flow()


@app.get("/nous/auth/status")
async def nous_auth_status():
    return nous_auth.token_manager.auth_status()
