FROM debian:bookworm-slim

# For production: override with a git tag (e.g., --build-arg HERMES_REF=v0.15.0) to pin version
ARG HERMES_REF=main

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers \
    HERMES_WEB_DIST=/opt/hermes/hermes_cli/web_dist

# System packages — Node.js 22 LTS from NodeSource
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates \
        python3 python3-pip python3-dev \
        ffmpeg tini ripgrep \
        build-essential libffi-dev \
        gosu \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# uv — fast Python package manager
RUN pip3 install uv --break-system-packages

# Clone hermes-agent at build time (pin HERMES_REF to a tag for production)
RUN git clone --depth 1 \
    https://github.com/NousResearch/hermes-agent.git \
    /opt/hermes

WORKDIR /opt/hermes

# Python deps — messaging extras covers Telegram, Discord, WhatsApp, Slack gateways
RUN uv sync --extra messaging --extra web

# Node.js agent-browser dependency (root-level, no build step)
RUN npm ci

# Web UI — install deps and build assets into hermes_cli/web_dist at image build time
# so the dashboard can start without running npm at runtime as unprivileged user
RUN cd web && npm install --prefer-offline --no-audit && npm run build

# Editable install so hermes CLI is properly importable
RUN uv pip install --no-cache-dir --no-deps -e "."

# Non-root user — uid 10000 matches official image default;
# entrypoint.sh remaps to HERMES_UID/HERMES_GID (1000/100) at runtime via gosu
RUN useradd -u 10000 -m -s /bin/bash hermes && \
    mkdir -p /opt/playwright-browsers && \
    chown -R hermes /opt/hermes /opt/playwright-browsers

VOLUME /opt/data

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/hermes/docker/entrypoint.sh"]
CMD ["gateway", "run"]
