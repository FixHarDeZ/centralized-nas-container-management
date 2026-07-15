import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager

import cohere
import llm_client
import nous_auth
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from encoder import load_encoder
from pydantic import BaseModel
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Fusion,
    FusionQuery,
    Prefetch,
    SparseVector,
)

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
- If context contains PARTIAL information, report what was found rather than saying "not found"
- Only say "not found" when ALL context blocks are completely unrelated to the question
- If context is truly insufficient, say:
    Thai: "ไม่พบข้อมูลในบันทึก ลองเพิ่มหัวข้อ: <suggested topic>"
    English: "Not found in notes. Consider adding: <suggested topic>"
- Cite sources inline with [1] [2] [3]
- Be concise, use bullet points for lists
- If ambiguous, ask ONE clarifying question"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global qdrant
    provider = os.getenv("LLM_PROVIDER", "anthropic")
    log.info("Loading BGE-M3 encoder…")
    app.state.model, backend = load_encoder()
    log.info("BGE-M3 loaded (backend=%s)", backend)

    # Keep-warm: periodic dummy encode so model pages stay resident in RAM
    # (cold query after idle was ~152s due to swap-out on the NAS).
    warm_interval = int(os.getenv("WARM_INTERVAL_SEC", "300"))

    async def _keep_warm():
        while True:
            await asyncio.sleep(warm_interval)
            try:
                t = time.monotonic()
                await asyncio.to_thread(
                    app.state.model.encode,
                    ["ping"],
                    return_dense=True,
                    return_sparse=True,
                )
                log.debug("keep-warm encode: %.0f ms", (time.monotonic() - t) * 1000)
            except Exception as exc:
                log.warning("keep-warm failed: %s", exc)

    warm_task = asyncio.create_task(_keep_warm()) if warm_interval > 0 else None
    log.info("LLM provider: %s | model: %s", provider, _active_model_name(provider))
    if COHERE_API_KEY:
        app.state.cohere = cohere.AsyncClientV2(api_key=COHERE_API_KEY)
    qdrant = AsyncQdrantClient(url=QDRANT_URL)
    yield
    if warm_task:
        warm_task.cancel()
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
    top_k_final: int = 6
    session_id: str = ""


@app.post("/query")
async def query(req: QueryRequest):
    t0 = time.monotonic()

    model = app.state.model

    # Encode runs on CPU — run in thread to avoid blocking the event loop
    out = await asyncio.to_thread(
        model.encode,
        [req.question],
        return_dense=True,
        return_sparse=True,
    )

    t_embed = time.monotonic()
    log.info("stage=embed ms=%d", int((t_embed - t0) * 1000))

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

    t_retrieve = time.monotonic()
    log.info("stage=retrieve ms=%d hits=%d", int((t_retrieve - t_embed) * 1000), len(hits))

    retrieval_method = "hybrid"
    if COHERE_API_KEY:
        co: cohere.AsyncClientV2 = app.state.cohere
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

    t_rerank = time.monotonic()
    log.info("stage=rerank ms=%d method=%s", int((t_rerank - t_retrieve) * 1000), retrieval_method)

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

    t_llm = time.monotonic()
    log.info("stage=llm ms=%d", int((t_llm - t_rerank) * 1000))

    cited_indices = sorted({int(m) - 1 for m in re.findall(r"\[(\d+)\]", answer)})
    cited_hits = [hits[i] for i in cited_indices if i < len(hits)]
    sources = [
        {
            "breadcrumb": h.payload.get("breadcrumb", ""),
            "page_url": h.payload.get("page_url", ""),
            "score": float(h.score),
        }
        for h in cited_hits
    ]

    latency_ms = int((time.monotonic() - t0) * 1000)
    log.info(
        "stage=total ms=%d (embed=%d retrieve=%d rerank=%d llm=%d)",
        latency_ms,
        int((t_embed - t0) * 1000),
        int((t_retrieve - t_embed) * 1000),
        int((t_rerank - t_retrieve) * 1000),
        int((t_llm - t_rerank) * 1000),
    )
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
async def ingest_trigger(full: bool = False, page_id: str = ""):
    try:
        env = os.environ.copy()
        if full:
            env["FULL_INGEST"] = "1"
        cmd = ["python", "/ingest/ingest.py"]
        if page_id:
            cmd.extend(["--page", page_id])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        combined = (stdout + stderr).decode(errors="replace")
        if proc.returncode == 0:
            return {"status": "done", "summary": combined}
        return JSONResponse(
            status_code=500,
            content={"status": "error", "summary": combined},
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "summary": str(exc)},
        )


@app.get("/nous/auth")
async def nous_auth_start():
    try:
        return await nous_auth.token_manager.start_device_flow()
    except Exception as exc:
        log.error("Nous device flow failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"error": "Nous Portal unavailable", "details": str(exc)},
        )


@app.get("/nous/auth/status")
async def nous_auth_status():
    return nous_auth.token_manager.auth_status()
