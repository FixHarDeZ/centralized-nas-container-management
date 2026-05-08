#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

# ── Load config ──────────────────────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: Config file not found: $ENV_FILE"
  echo "Copy .env.example to .env and fill in your NAS details."
  exit 1
fi

# shellcheck source=.env
source "$ENV_FILE"

NAS_USER="${NAS_USER:?NAS_USER is not set in $ENV_FILE}"
NAS_HOST="${NAS_HOST:?NAS_HOST is not set in $ENV_FILE}"
NAS_PORT="${NAS_PORT:-2222}"
NAS_TARGET_PATH="${NAS_TARGET_PATH:-/volume1/docker}"
NAS_SSH_KEY="${NAS_SSH_KEY:-${HOME}/.ssh/id_ed25519}"
NAS_SUDO_PASSWORD="${NAS_SUDO_PASSWORD:-}"
# Optional: set NAS_SSH_ALIAS=nas in .env to use your ssh config alias directly
# (more compatible with macOS Keychain — if explicit params fail, try this)
NAS_SSH_ALIAS="${NAS_SSH_ALIAS:-}"

# ── Dependency check ─────────────────────────────────────────────────────────
if ! command -v rsync &>/dev/null; then
  echo "ERROR: 'rsync' is required but not installed."
  exit 1
fi

# ── SSH setup — multiplexing keeps one connection alive for all commands ──────
MUX_SOCKET="/tmp/nas_deploy_mux_$$"

if [[ -n "${NAS_SSH_ALIAS}" ]]; then
  SSH_DEST="${NAS_SSH_ALIAS}"
  SSH_BASE="-o ConnectTimeout=15"
else
  SSH_DEST="${NAS_USER}@${NAS_HOST}"
  SSH_BASE="-o StrictHostKeyChecking=no -o ConnectTimeout=15 -p ${NAS_PORT} -i ${NAS_SSH_KEY}"
fi

# Multiplexing options shared by all commands
SSH_MUX="-o ControlMaster=auto -o ControlPath=${MUX_SOCKET} -o ControlPersist=120"
SSH_OPTS="${SSH_BASE} ${SSH_MUX}"

# Clean up mux socket on script exit
trap 'ssh -o ControlPath="${MUX_SOCKET}" -O exit "${SSH_DEST}" 2>/dev/null; rm -f "${MUX_SOCKET}"' EXIT

# ── Connection check — establishes the mux master ────────────────────────────
echo "Checking connection to ${NAS_USER}@${NAS_HOST}:${NAS_PORT} ..."
if ! ssh $SSH_OPTS "${SSH_DEST}" "echo OK" &>/dev/null; then
  echo "ERROR: Cannot connect to NAS. Check host, port, and SSH key."
  echo "  SSH key: ${NAS_SSH_KEY}"
  if [[ -z "${NAS_SSH_ALIAS}" ]]; then
    echo "  Tip: add NAS_SSH_ALIAS=nas to .env to use your ssh config alias"
  fi
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
  --exclude='./.env' \
  --exclude='./deploy.sh' \
  -C "${SCRIPT_DIR}" . \
  | ssh $SSH_OPTS "${SSH_DEST}" \
    "mkdir -p '${NAS_TARGET_PATH}' && tar -xzf - -C '${NAS_TARGET_PATH}' --no-same-permissions --no-same-owner 2>/dev/null; exit 0"

# ── Upload root .env to NAS ───────────────────────────────────────────────────
echo "Uploading .env ..."
ssh $SSH_OPTS "${SSH_DEST}" "cat > '${NAS_TARGET_PATH}/.env'" < "${ENV_FILE}"

echo ""
echo "Done. Files uploaded to ${NAS_TARGET_PATH} on NAS."

# ── Restart stacks ───────────────────────────────────────────────────────────
if [[ -z "${NAS_SUDO_PASSWORD}" ]]; then
  echo ""
  echo "NAS_SUDO_PASSWORD not set in .env — skipping stack restart."
  echo "To enable auto-restart, add NAS_SUDO_PASSWORD=your_password to .env."
  exit 0
fi

STACKS=(torrentwatch line-secretary homepage jellyfin maid-tracker portainer uptime-kuma watchtower)

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
  ssh $SSH_OPTS "${SSH_DEST}" \
    "bash -l -c \"echo '${NAS_SUDO_PASSWORD}' | sudo -S docker compose --env-file '${NAS_TARGET_PATH}/.env' -f '${NAS_TARGET_PATH}/${stack}/docker-compose.yml' down && echo '${NAS_SUDO_PASSWORD}' | sudo -S docker compose --env-file '${NAS_TARGET_PATH}/.env' -f '${NAS_TARGET_PATH}/${stack}/docker-compose.yml' up -d --build\""
  echo ""
done

echo "All done."
