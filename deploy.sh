#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.deploy.env"

# ── Load config ──────────────────────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: Config file not found: $ENV_FILE"
  echo "Copy .deploy.env.example to .deploy.env and fill in your credentials."
  exit 1
fi

# shellcheck source=.deploy.env
source "$ENV_FILE"

NAS_USER="${NAS_USER:?NAS_USER is not set in $ENV_FILE}"
NAS_HOST="${NAS_HOST:?NAS_HOST is not set in $ENV_FILE}"
NAS_PORT="${NAS_PORT:-22}"
NAS_PASSWORD="${NAS_PASSWORD:?NAS_PASSWORD is not set in $ENV_FILE}"
NAS_TARGET_PATH="${NAS_TARGET_PATH:-/volume1/docker}"

# ── Dependency check ─────────────────────────────────────────────────────────
if ! command -v sshpass &>/dev/null; then
  echo "ERROR: 'sshpass' is required but not installed."
  echo "  macOS:  brew install sshpass"
  echo "  Debian: apt-get install sshpass"
  exit 1
fi

if ! command -v rsync &>/dev/null; then
  echo "ERROR: 'rsync' is required but not installed."
  exit 1
fi

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10 -p ${NAS_PORT}"
SSHPASS="sshpass -p ${NAS_PASSWORD}"

# ── Connection check ─────────────────────────────────────────────────────────
echo "Checking connection to ${NAS_USER}@${NAS_HOST}:${NAS_PORT} ..."
if ! $SSHPASS ssh $SSH_OPTS "${NAS_USER}@${NAS_HOST}" "echo OK" &>/dev/null; then
  echo "ERROR: Cannot connect to NAS. Check host, port, username, and password."
  exit 1
fi
echo "Connection OK."

# ── Confirm ──────────────────────────────────────────────────────────────────
echo ""
echo "Target : ${NAS_USER}@${NAS_HOST}:${NAS_TARGET_PATH}"
echo "Source : ${SCRIPT_DIR}/"
echo ""
read -r -p "Upload now? [y/N] " CONFIRM
if [[ ! "${CONFIRM}" =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 0
fi

# ── Upload ───────────────────────────────────────────────────────────────────
echo ""
echo "Uploading ..."
echo ""

COPYFILE_DISABLE=1 tar -czf - \
  --exclude='./.git' \
  --exclude='./.deploy.env' \
  --exclude='./deploy.sh' \
  -C "${SCRIPT_DIR}" . \
  | $SSHPASS ssh $SSH_OPTS "${NAS_USER}@${NAS_HOST}" \
    "mkdir -p '${NAS_TARGET_PATH}' && tar -xzf - -C '${NAS_TARGET_PATH}' --no-same-permissions --no-same-owner 2>/dev/null; exit 0"

echo ""
echo "Done. Files uploaded to ${NAS_TARGET_PATH} on NAS."

# ── Restart stacks ───────────────────────────────────────────────────────────
STACKS=(homepage jellyfin maid-tracker portainer uptime-kuma watchtower)

echo ""
echo "Stacks available: ${STACKS[*]}"
read -r -p "Restart all stacks on NAS now? [y/N] " RESTART_ALL
if [[ "${RESTART_ALL}" =~ ^[Yy]$ ]]; then
  STACKS_TO_RESTART=("${STACKS[@]}")
else
  STACKS_TO_RESTART=()
  for stack in "${STACKS[@]}"; do
    read -r -p "  Restart ${stack}? [y/N] " RESTART_STACK
    if [[ "${RESTART_STACK}" =~ ^[Yy]$ ]]; then
      STACKS_TO_RESTART+=("$stack")
    fi
  done
fi

if [[ ${#STACKS_TO_RESTART[@]} -eq 0 ]]; then
  echo "No stacks selected. Done."
  exit 0
fi

echo ""
echo "Restarting: ${STACKS_TO_RESTART[*]}"
echo ""

for stack in "${STACKS_TO_RESTART[@]}"; do
  echo "── ${stack} ──────────────────────────────────────────"
  $SSHPASS ssh $SSH_OPTS "${NAS_USER}@${NAS_HOST}" \
    "bash -l -c \"echo '${NAS_PASSWORD}' | sudo -S docker compose -f '${NAS_TARGET_PATH}/${stack}/docker-compose.yml' down && echo '${NAS_PASSWORD}' | sudo -S docker compose -f '${NAS_TARGET_PATH}/${stack}/docker-compose.yml' up -d --build\""
  echo ""
done

echo "All done."
