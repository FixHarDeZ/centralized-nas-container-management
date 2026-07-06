FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && curl -fsSL -o /tmp/gh.tar.gz https://github.com/cli/cli/releases/download/v2.63.2/gh_2.63.2_linux_amd64.tar.gz \
    && tar -xz -C /usr/local --strip-components=2 -f /tmp/gh.tar.gz gh_2.63.2_linux_amd64/bin/gh \
    && rm -f /tmp/gh.tar.gz \
    && curl -fsSL -o /tmp/docker.tgz https://download.docker.com/linux/static/stable/x86_64/docker-27.3.1.tgz \
    && tar -xz -C /usr/local/bin --strip-components=1 -f /tmp/docker.tgz docker/docker \
    && rm -f /tmp/docker.tgz \
    && mkdir -p /usr/local/lib/docker/cli-plugins \
    && curl -fsSL -o /usr/local/lib/docker/cli-plugins/docker-compose \
       https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-x86_64 \
    && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY prompts/ ./prompts/
COPY config.yaml .

RUN mkdir -p /data /workspaces

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5070"]
