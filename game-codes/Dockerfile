FROM python:3.12-slim

RUN groupadd -g 1000 app && useradd -u 1000 -g app -s /bin/sh app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app config.py parsers.py state.py notify.py http_client.py game_code_notifier.py ./

RUN mkdir -p /data && chown app:app /data

USER app
CMD ["python", "game_code_notifier.py"]
