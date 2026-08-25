FROM python:3.12-slim

# tzdata: without it TZ=Asia/Bangkok is ignored
# ffmpeg: assembles the cards into the clip
# libraqm0: Pillow's manylinux wheel does NOT bundle Raqm — without this package
#   ImageFont.Layout.RAQM silently falls back to basic layout and Thai tone marks
#   are dropped (only a UserWarning). See docs/adr/0003.
# fonts-thai-tlwg: Waree-Bold covers Thai AND Latin. Noto Sans Thai does not —
#   its cmap has no A-Z/a-z/0-9 at all, so "เก็บ log ไว้" renders the Latin word
#   as tofu boxes, and Pillow has no font fallback to rescue it.
# fonts-dejavu-core: monospace face for code blocks
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata ffmpeg libraqm0 fonts-thai-tlwg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Fail the build rather than ship an image that mangles Thai.
RUN python -c "from PIL import features; assert features.check('raqm'), 'Raqm missing'"

COPY app/ app/
COPY tests/ tests/

CMD ["python", "-m", "app.main"]
