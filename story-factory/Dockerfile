FROM python:3.12-slim

# tzdata: without it TZ=Asia/Bangkok is ignored
# ffmpeg: draws the waveform over the Backdrop and encodes the Story in one pass
# fonts-thai-tlwg: Waree covers Thai AND Latin; Noto Sans Thai's cmap has no
#   A-Z/a-z/0-9 at all and Pillow has no font fallback. See docs/adr/0003.
# libraqm0: Pillow's manylinux wheel does NOT bundle Raqm — without it
#   ImageFont.Layout.RAQM falls back to basic layout and Thai tone marks vanish
#   with only a UserWarning.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata ffmpeg libraqm0 fonts-thai-tlwg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Fail the build rather than ship an image that mangles Thai.
RUN python -c "from PIL import features; assert features.check('raqm'), 'Raqm missing'"

COPY app/ app/
COPY tests/ tests/

CMD ["python", "-m", "app.main"]
