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
