FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# CPU-only torch first to avoid pulling CUDA (~200MB vs ~2.5GB)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

# Build-time: download BGE-M3 ONNX export + quantize to int8 (~600MB baked in).
# Non-fatal on failure — encoder.py falls back to torch/FlagEmbedding at runtime.
COPY export_onnx.py .
RUN python export_onnx.py || echo "WARN: ONNX export failed; runtime will use torch fallback"

COPY main.py llm_client.py nous_auth.py encoder.py .

EXPOSE 5065

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5065/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5065"]
