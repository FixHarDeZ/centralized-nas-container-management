# claude-desk — Claude Code as a document desk, reached from a phone browser.
#
# One image, one process: ttyd serving a tmux session. The nginx sidecar
# (docker-compose.yml) owns the port, the basic auth and the static UI; this
# container is never published on the host.
#
# Pinned on purpose: bump CLAUDE_VERSION / SKILLS_REF by hand and redeploy.
# The image is built locally so watchtower never touches it (see compose
# labels) — nothing here changes unless someone edits these ARGs.

# Node 22 LTS — copied out of the official image rather than installed from
# NodeSource, same trick hermes-agent uses.
FROM node:22-bookworm-slim AS node_source

FROM debian:bookworm-slim

ARG CLAUDE_VERSION=2.1.272
ARG SKILLS_REF=34040c9c568585f6929bedeaad110ad08f079624
ARG TTYD_VERSION=1.7.7
ARG TTYD_SHA256=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55
ARG RTK_VERSION=0.49.0
ARG RTK_SHA256=7278231dfd7e6a730a4ab7f847b195bcf02289c2d57622b0dab75a6411100c8f

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Asia/Bangkok

# The office skills call soffice (pptx/docx/xlsx → pdf → png so Claude can
# look at what it produced), qpdf/pdftoppm for the pdf skill, and Thai fonts
# so a Thai deck renders with real glyphs instead of tofu in the preview.
# *-nogui variants skip the X/GTK stack — headless is all we ever run.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git tmux procps less unzip zip jq ripgrep \
        python3 python3-pip python3-venv python-is-python3 \
        libreoffice-core-nogui libreoffice-impress-nogui \
        libreoffice-writer-nogui libreoffice-calc-nogui \
        poppler-utils qpdf \
        fonts-liberation fonts-dejavu-core fonts-thai-tlwg fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

COPY --chmod=0755 --from=node_source /usr/local/bin/node /usr/local/bin/
COPY --from=node_source /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# ttyd — static release binary, checksum-verified.
RUN set -eu; \
    curl -fsSL --retry 3 -o /usr/local/bin/ttyd \
        "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64"; \
    echo "${TTYD_SHA256}  /usr/local/bin/ttyd" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/ttyd

# rtk — same token-trimming Bash hook the workstation uses (rtk hook claude
# rewrites Claude's Bash calls to `rtk <cmd>` and filters the output).
# Static musl build; wired in via claude-settings.json + entrypoint.sh.
RUN set -eu; \
    curl -fsSL --retry 3 -o /tmp/rtk.tgz \
        "https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}/rtk-x86_64-unknown-linux-musl.tar.gz"; \
    echo "${RTK_SHA256}  /tmp/rtk.tgz" | sha256sum -c -; \
    tar -xzf /tmp/rtk.tgz -C /usr/local/bin rtk; \
    chmod 0755 /usr/local/bin/rtk; rm /tmp/rtk.tgz; \
    rtk --version

# Claude Code + the node side of the office skills (pptxgenjs for decks,
# docx for documents, react-icons/sharp for icon rasterising). Global so the
# skills' bare require() finds them without an npm install per job.
RUN npm install -g --no-fund --no-audit \
        "@anthropic-ai/claude-code@${CLAUDE_VERSION}" \
        pptxgenjs docx react-icons react react-dom sharp \
    && npm cache clean --force

# Python side of the skills. --break-system-packages because this is a
# single-purpose image with no distro-python consumer to protect.
RUN pip3 install --no-cache-dir --break-system-packages \
        python-pptx python-docx openpyxl pandas pillow \
        pypdf pdfplumber reportlab pdf2image defusedxml lxml \
        "markitdown[pptx,docx,xlsx,pdf]"

# Official Anthropic skills, pinned. Only the office ones get linked into the
# home volume at start (entrypoint.sh) — the rest stay on disk unused.
RUN git clone --depth 1 https://github.com/anthropics/skills.git /opt/skills \
    && cd /opt/skills && git fetch --depth 1 origin "${SKILLS_REF}" \
    && git checkout -q "${SKILLS_REF}" && rm -rf .git

# Non-root uid 1000: Claude Code refuses --dangerously-skip-permissions as
# root. gid 100 = DSM's `users` group — the share's Synology ACL is what
# grants access (mode bits are 777 and mean nothing), and the ACL entry we
# rely on is group:users, so the process must carry that gid.
RUN useradd -u 1000 -g 100 -m -d /home/claude -s /bin/bash claude \
    && mkdir -p /work && chown claude:users /work

# --chmod everywhere: the tar|ssh upload lands files as 0700 and COPY keeps
# that; a 0700 root-owned tmux.conf is silently ignored by tmux as uid 1000.
COPY --chmod=0644 tmux.conf /etc/tmux.conf
# Baked in, not bind-mounted from ./work: directories under /volume2/docker
# carry the DSM share ACL and uid 1000 cannot read through them.
COPY --chmod=0644 work/CLAUDE.md /opt/claude-desk/work/CLAUDE.md
COPY --chmod=0644 claude-settings.json /opt/claude-desk/claude-settings.json
COPY --chmod=0644 upload.py /opt/claude-desk/upload.py
COPY --chmod=0644 profile.sh /etc/profile.d/claude-desk.sh
COPY --chmod=0755 entrypoint.sh /usr/local/bin/entrypoint.sh

# Global npm modules are not on require()'s path by default — the skills do a
# bare require('pptxgenjs') from /work, so expose them.
ENV NODE_PATH=/usr/local/lib/node_modules

# Build-time sanity: the pieces the skills lean on must actually be here.
RUN soffice --version | head -1 \
    && claude --version \
    && node -e "require('pptxgenjs'); require('docx')" \
    && python3 -c "import pptx, docx, openpyxl, markitdown, pypdf"

USER claude
WORKDIR /work
ENV HOME=/home/claude \
    TERM=xterm-256color \
    DISABLE_AUTOUPDATER=1

EXPOSE 7681 7682
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
