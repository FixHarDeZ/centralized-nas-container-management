FROM ghcr.io/astral-sh/uv:0.11.6-python3.13-trixie AS uv_source
# Node 22 LTS — bookworm-slim binary is glibc-compatible with our trixie runtime
FROM node:22-bookworm-slim AS node_source

FROM debian:13.4

ARG HERMES_REF=main

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/opt/hermes/.playwright \
    HERMES_WEB_DIST=/opt/hermes/hermes_cli/web_dist \
    npm_config_install_links=false

# System packages — no tini/gosu; s6-overlay takes over as PID 1
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git \
        python3 python-is-python3 \
        ripgrep ffmpeg \
        gcc python3-dev libffi-dev \
        procps openssh-client xz-utils \
    && rm -rf /var/lib/apt/lists/*

# ---------- s6-overlay 3.2.3.0 ----------
# Multi-arch: BuildKit auto-populates TARGETARCH (amd64 / arm64).
# SHA256-verified against upstream-published checksums.
ARG TARGETARCH
ARG S6_OVERLAY_VERSION=3.2.3.0
ARG S6_OVERLAY_NOARCH_SHA256=b720f9d9340efc8bb07528b9743813c836e4b02f8693d90241f047998b4c53cf
ARG S6_OVERLAY_X86_64_SHA256=a93f02882c6ed46b21e7adb5c0add86154f01236c93cd82c7d682722e8840563
ARG S6_OVERLAY_AARCH64_SHA256=0952056ff913482163cc30e35b2e944b507ba1025d78f5becbb89367bf344581
ARG S6_OVERLAY_SYMLINKS_SHA256=a60dc5235de3ecbcf874b9c1f18d73263ab99b289b9329aa950e8729c4789f0e
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz /tmp/
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-symlinks-noarch.tar.xz /tmp/
RUN set -eu; \
    case "${TARGETARCH:-amd64}" in \
        amd64) s6_arch="x86_64"; s6_arch_sha="${S6_OVERLAY_X86_64_SHA256}" ;; \
        arm64) s6_arch="aarch64"; s6_arch_sha="${S6_OVERLAY_AARCH64_SHA256}" ;; \
        *) echo "Unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL --retry 3 -o /tmp/s6-overlay-arch.tar.xz \
        "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${s6_arch}.tar.xz"; \
    { \
        printf '%s  %s\n' "${S6_OVERLAY_NOARCH_SHA256}" /tmp/s6-overlay-noarch.tar.xz; \
        printf '%s  %s\n' "${s6_arch_sha}" /tmp/s6-overlay-arch.tar.xz; \
        printf '%s  %s\n' "${S6_OVERLAY_SYMLINKS_SHA256}" /tmp/s6-overlay-symlinks-noarch.tar.xz; \
    } > /tmp/s6-overlay.sha256; \
    sha256sum -c /tmp/s6-overlay.sha256; \
    tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz; \
    tar -C / -Jxpf /tmp/s6-overlay-arch.tar.xz; \
    tar -C / -Jxpf /tmp/s6-overlay-symlinks-noarch.tar.xz; \
    rm /tmp/s6-overlay-*.tar.xz /tmp/s6-overlay.sha256

# uv — from official uv image (faster + pinned version)
COPY --chmod=0755 --from=uv_source /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/

# Node 22 LTS — copy binary + npm + corepack from upstream image
COPY --chmod=0755 --from=node_source /usr/local/bin/node /usr/local/bin/
COPY --from=node_source /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
COPY --from=node_source /usr/local/lib/node_modules/corepack /usr/local/lib/node_modules/corepack
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx && \
    ln -sf /usr/local/lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack

# Non-root user — uid 10000, home = HERMES_HOME (/opt/data on the volume)
RUN useradd -u 10000 -m -d /opt/data -s /bin/bash hermes

# Clone hermes-agent at build time (pin HERMES_REF to a tag for production)
RUN git clone --depth 1 --branch ${HERMES_REF} \
    https://github.com/NousResearch/hermes-agent.git \
    /opt/hermes

WORKDIR /opt/hermes

# Python deps — messaging + web extras cover gateway, Discord/Telegram, and dashboard
RUN uv sync --extra messaging --extra web

# Node deps + Playwright Chromium + web/ui-tui frontend deps
RUN npm install --prefer-offline --no-audit && \
    npx playwright install --with-deps chromium --only-shell && \
    (cd web && npm install --prefer-offline --no-audit) && \
    (cd ui-tui && npm install --prefer-offline --no-audit) && \
    npm cache clean --force

# Build web dashboard and terminal UI assets
RUN cd web && npm run build && \
    cd ../ui-tui && npm run build

# Editable install so hermes CLI is properly importable
RUN uv pip install --no-cache-dir --no-deps -e "."

# ---------- s6-overlay wiring (sourced from cloned repo) ----------
# cont-init.d/01: stage2-hook handles UID/GID remap, volume chown, config seeding
# cont-init.d/015, 02: supervise-perms and profile reconciler
RUN mkdir -p /etc/s6-overlay/s6-rc.d && \
    cp -r /opt/hermes/docker/s6-rc.d/. /etc/s6-overlay/s6-rc.d/ && \
    mkdir -p /etc/cont-init.d && \
    printf '#!/command/with-contenv sh\nexec /opt/hermes/docker/stage2-hook.sh\n' \
        > /etc/cont-init.d/01-hermes-setup && \
    chmod +x /etc/cont-init.d/01-hermes-setup && \
    cp /opt/hermes/docker/cont-init.d/015-supervise-perms /etc/cont-init.d/ && \
    chmod +x /etc/cont-init.d/015-supervise-perms && \
    cp /opt/hermes/docker/cont-init.d/02-reconcile-profiles /etc/cont-init.d/ && \
    chmod +x /etc/cont-init.d/02-reconcile-profiles

# exec shim: privilege-drop wrapper so `docker exec <c> hermes ...` runs as hermes user
RUN mkdir -p /opt/hermes/bin && \
    cp /opt/hermes/docker/hermes-exec-shim.sh /opt/hermes/bin/hermes && \
    chmod +x /opt/hermes/bin/hermes

# Permissions: world-readable tree; hermes owns write-critical subdirs
RUN chmod -R a+rX /opt/hermes && \
    chown -R hermes:hermes /opt/hermes/.venv /opt/hermes/ui-tui /opt/hermes/node_modules

RUN mkdir -p /opt/data

VOLUME /opt/data

ENV PATH="/opt/hermes/bin:/opt/hermes/.venv/bin:/opt/data/.local/bin:${PATH}"
ENV HERMES_HOME=/opt/data

# /init (s6-overlay) is PID 1 — runs cont-init.d, starts s6-rc.d services,
# then execs main-wrapper.sh as the container's main program (CMD passthrough).
ENTRYPOINT ["/init", "/opt/hermes/docker/main-wrapper.sh"]
CMD []
