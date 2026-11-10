#!/usr/bin/env bash
# Update hermes-agent to a specific upstream tag.
#
# Usage:
#   ./scripts/update-hermes.sh v2026.5.28
#
# The script will:
#   1. Verify the target tag exists in NousResearch/hermes-agent
#   2. Verify it does NOT contain stage2-hook.sh (= s6-overlay migration is incomplete)
#   3. Update HERMES_REF in docker-compose.yml
#   4. Deploy (upload + rebuild image on NAS + restart)
#   5. Commit docker-compose.yml to main and push to origin
#
# Requires: gh CLI, bash scripts/deploy.sh (with .env configured), on branch main

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE="hermes-agent/docker-compose.yml"
UPSTREAM_REPO="NousResearch/hermes-agent"
GIT_BRANCH="main"

usage() {
    echo "Usage: $0 <tag>"
    echo "  Example: $0 v2026.5.28"
    exit 1
}

[[ $# -lt 1 ]] && usage
TARGET_TAG="$1"

echo "==> Checking git state ..."
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$CURRENT_BRANCH" != "$GIT_BRANCH" ]]; then
    echo "ERROR: On branch '${CURRENT_BRANCH}', expected '${GIT_BRANCH}'"
    exit 1
fi
# Only a pending HERMES_REF bump may be uncommitted in the compose file —
# anything else would ride along in the bump commit.
if git diff -U0 HEAD -- "$COMPOSE_FILE" | grep -E '^[+-][^+-]' | grep -vq 'HERMES_REF:'; then
    echo "ERROR: ${COMPOSE_FILE} has uncommitted changes other than HERMES_REF."
    echo "       Commit or stash them first."
    exit 1
fi
git fetch --quiet origin "$GIT_BRANCH"
if [[ -n "$(git rev-list "HEAD..origin/${GIT_BRANCH}")" ]]; then
    echo "ERROR: Local ${GIT_BRANCH} is behind origin/${GIT_BRANCH}. Pull first."
    exit 1
fi
echo "    ✔ On ${GIT_BRANCH}, up to date with origin"

echo "==> Checking tag '${TARGET_TAG}' on ${UPSTREAM_REPO} ..."
if ! gh api "repos/${UPSTREAM_REPO}/git/ref/tags/${TARGET_TAG}" --jq '.ref' &>/dev/null; then
    echo "ERROR: Tag '${TARGET_TAG}' not found on ${UPSTREAM_REPO}"
    exit 1
fi
echo "    ✔ Tag exists"

echo "==> Checking for s6-overlay in '${TARGET_TAG}' ..."
HTTP_STATUS=$(gh api "repos/${UPSTREAM_REPO}/contents/docker/stage2-hook.sh?ref=${TARGET_TAG}" \
    --jq '.name' 2>&1) || true

if echo "$HTTP_STATUS" | grep -q "Not Found"; then
    echo "ERROR: '${TARGET_TAG}' does not contain docker/stage2-hook.sh."
    echo "       This tag predates the s6-overlay migration. Our Dockerfile requires"
    echo "       s6-overlay (tags >= v2026.5.29.2). Use a newer tag."
    exit 1
fi
echo "    ✔ s6-overlay present — safe to use"

# The tag's .npmrc sets engine-strict=true, so a node_source image older than
# package.json "engines.node" fails `npm install` with EBADENGINE mid-build
# (v0.22.7 dropped node 22). Catch it here instead of after upload + 45 s of build.
echo "==> Checking node engines for '${TARGET_TAG}' ..."
ENGINES_NODE=$(gh api "repos/${UPSTREAM_REPO}/contents/package.json?ref=${TARGET_TAG}" \
    --jq '.content' | base64 --decode | python3 -c 'import json,sys; print(json.load(sys.stdin).get("engines",{}).get("node",""))')
NODE_IMAGE=$(grep -Eo 'FROM node:[^ ]+' hermes-agent/Dockerfile | head -1 | cut -d: -f2)
NODE_MAJOR=${NODE_IMAGE%%[.-]*}
# Every range clause's lower bound major; the image passes if it meets any clause.
if ! python3 - "$ENGINES_NODE" "$NODE_MAJOR" <<'PY'
import re, sys
rng, major = sys.argv[1], int(sys.argv[2])
if not rng:
    sys.exit(0)
ok = False
for clause in rng.split("||"):
    m = re.search(r"(\d+)", clause)
    if not m:
        continue
    lo = int(m.group(1))
    # ^N / N.x / ~N pin the major; >=N is open-ended.
    ok |= (major >= lo) if ">=" in clause else (major == lo)
sys.exit(0 if ok else 1)
PY
then
    echo "ERROR: '${TARGET_TAG}' needs node '${ENGINES_NODE}', Dockerfile uses node:${NODE_IMAGE}."
    echo "       Bump node_source in hermes-agent/Dockerfile (match upstream pm/lock.json node)"
    echo "       and check its bundled npm against engines.npm."
    exit 1
fi
echo "    ✔ node:${NODE_IMAGE} satisfies '${ENGINES_NODE}'"

# v0.23.1 switched the repo to pnpm: engines.npm became "npm is refused here …"
# and package-lock.json disappeared, so a Dockerfile still running `npm install`
# in the repo fails with EBADENGINE mid-build (2026-11-10). Catch it here.
echo "==> Checking package manager for '${TARGET_TAG}' ..."
PKG_JSON=$(gh api "repos/${UPSTREAM_REPO}/contents/package.json?ref=${TARGET_TAG}" --jq '.content' | base64 --decode)
ENGINES_NPM=$(printf '%s' "$PKG_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("engines",{}).get("npm",""))')
USES_PNPM=0
if gh api "repos/${UPSTREAM_REPO}/contents/pnpm-lock.yaml?ref=${TARGET_TAG}" --jq '.name' &>/dev/null; then USES_PNPM=1; fi
DOCKERFILE_NPM_INSTALL=0
if grep -Ev '^[[:space:]]*#' hermes-agent/Dockerfile | grep -Eq '(^|[^x])npm (install|ci)'; then DOCKERFILE_NPM_INSTALL=1; fi
DOCKERFILE_PNPM=0
if grep -q 'node-deps.mjs' hermes-agent/Dockerfile; then DOCKERFILE_PNPM=1; fi
if [[ "$USES_PNPM" == 1 && "$DOCKERFILE_PNPM" == 0 ]] || { [[ "$ENGINES_NPM" == *refused* ]] && [[ "$DOCKERFILE_NPM_INSTALL" == 1 ]]; }; then
    echo "ERROR: '${TARGET_TAG}' installs with pnpm (engines.npm: '${ENGINES_NPM}'),"
    echo "       but hermes-agent/Dockerfile still installs the repo with npm."
    echo "       Port the install/build steps (see the pnpm block in the Dockerfile)."
    exit 1
fi
if [[ "$USES_PNPM" == 0 && "$DOCKERFILE_PNPM" == 1 ]]; then
    echo "ERROR: '${TARGET_TAG}' has no pnpm-lock.yaml but the Dockerfile builds with pnpm (node-deps.mjs)."
    exit 1
fi
echo "    ✔ package manager matches ($( [[ $USES_PNPM == 1 ]] && echo pnpm || echo npm ))"

CURRENT_TAG=$(grep 'HERMES_REF:' "$COMPOSE_FILE" | awk '{print $2}')
echo "==> Updating HERMES_REF: ${CURRENT_TAG} -> ${TARGET_TAG} in ${COMPOSE_FILE}"
sed -i.bak "s/HERMES_REF: .*/HERMES_REF: ${TARGET_TAG}/" "$COMPOSE_FILE" && rm -f "${COMPOSE_FILE}.bak"

echo ""
echo "==> Running deploy ..."
bash "${SCRIPT_DIR}/deploy.sh" -s hermes-agent -y

echo ""
echo "==> Committing ${COMPOSE_FILE} ..."
if git diff --quiet HEAD -- "$COMPOSE_FILE"; then
    echo "    HERMES_REF already ${TARGET_TAG} in HEAD — nothing to commit"
else
    # Pathspec commit: only the compose file, even if other files are staged.
    git commit --quiet -m "chore(hermes-agent): bump HERMES_REF to ${TARGET_TAG}" -- "$COMPOSE_FILE"
    echo "    ✔ $(git log -1 --oneline)"
fi

echo "==> Pushing to origin/${GIT_BRANCH} ..."
git push origin "$GIT_BRANCH"

echo ""
echo "==> Update complete. New ref: ${TARGET_TAG}"
