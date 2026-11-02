FROM python:3.12-slim

RUN groupadd -g 1000 app && useradd -u 1000 -g app -s /bin/sh app

WORKDIR /app
# openai is only for the vendored app/mimo.py; everything else is stdlib.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app config.json ./
COPY --chown=app:app app/ ./app/
RUN mkdir -p /data && chown app:app /data

USER app
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "app.main"]
