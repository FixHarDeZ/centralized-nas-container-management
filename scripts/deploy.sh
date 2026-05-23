#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"
START_TS=$(date +%s)

# ── Colors ───────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  C_RESET='\033[0m'; C_BOLD='\033[1m'
  C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'
  C_CYAN='\033[0;36m'; C_RED='\033[0;31m'; C_DIM='\033[2m'
else
  C_RESET=''; C_BOLD=''; C_GREEN=''; C_YELLOW=''; C_CYAN=''; C_RED=''; C_DIM=''
fi

log()  { printf "${C_BOLD}${C_CYAN}▶ %s${C_RESET}\n" "$*"; }
ok()   { printf "${C_GREEN}✔ %s${C_RESET}\n" "$*"; }
warn() { printf "${C_YELLOW}⚠ %s${C_RESET}\n" "$*"; }
err()  { printf "${C_RED}✘ %s${C_RESET}\n" "$*" >&2; }
dim()  { printf "${C_DIM}  %s${C_RESET}\n" "$*"; }

elapsed() { echo "$(( $(date +%s) - START_TS ))s"; }

# ── CLI flags ────────────────────────────────────────────────────────────────
STACKS_ARG=""
UPLOAD_ONLY=false
RESTART_ONLY=false
DRY_RUN=false
AUTO_YES=false

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  -s, --stacks STACKS   Comma-separated stacks to restart, or "all"
      --upload-only     Upload files only, skip restart
      --restart-only    Restart stacks only, skip upload
      --dry-run         Show what would happen without doing it
  -y, --yes             Skip upload confirmation prompt
  -h, --help            Show this help

Examples:
  $(basename "$0")                          # Interactive (default)
  $(basename "$0") -s maid-tracker,homepage # Upload + restart specific stacks
  $(basename "$0") -s all -y               # Upload + restart all (no prompt)
  $(basename "$0") --restart-only -s all   # Restart all without re-uploading
  $(basename "$0") --dry-run               # Preview rsync diff only
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--stacks)     STACKS_ARG="$2"; shift 2 ;;
    --upload-only)   UPLOAD_ONLY=true; shift ;;
    --restart-only)  RESTART_ONLY=true; shift ;;
    --dry-run)       DRY_RUN=true; shift ;;
    -y|--yes)        AUTO_YES=true; shift ;;
    -h|--help)       usage; exit 0 ;;
    *) err "Unknown option: $1"; usage; exit 1 ;;
  esac
done

# ── Load config ──────────────────────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
  err "Config file not found: $ENV_FILE"
  echo "  Copy .env.example to .env and fill in your NAS details."
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
# Optional: set NAS_SSH_ALIAS=nas in .env to use your ssh config alias
NAS_SSH_ALIAS="${NAS_SSH_ALIAS:-}"

# ── Dependency check ─────────────────────────────────────────────────────────
for dep in rsync ssh; do
  if ! command -v "$dep" &>/dev/null; then
    err "'$dep' is required but not installed."
    exit 1
  fi
done

# ── SSH setup — multiplexing keeps one connection alive for all commands ──────
MUX_SOCKET="/tmp/nas_deploy_mux_$$"
SSH_WRAPPER=""   # set later; referenced in trap for cleanup

if [[ -n "${NAS_SSH_ALIAS}" ]]; then
  SSH_DEST="${NAS_SSH_ALIAS}"
  SSH_BASE="-o ConnectTimeout=15"
else
  SSH_DEST="${NAS_USER}@${NAS_HOST}"
  SSH_BASE="-o StrictHostKeyChecking=no -o ConnectTimeout=15 -p ${NAS_PORT} -i ${NAS_SSH_KEY}"
fi

SSH_MUX="-o ControlMaster=auto -o ControlPath=${MUX_SOCKET} -o ControlPersist=120"
SSH_OPTS="${SSH_BASE} ${SSH_MUX}"

trap 'ssh -o ControlPath="${MUX_SOCKET}" -O exit "${SSH_DEST}" 2>/dev/null; rm -f "${MUX_SOCKET}" "${SSH_WRAPPER:-}"' EXIT

# ── Connection check — establishes the mux master ────────────────────────────
log "Connecting to ${SSH_DEST} ..."
if ! ssh $SSH_OPTS "${SSH_DEST}" "echo OK" &>/dev/null; then
  err "Cannot connect to NAS. Check host, port, and SSH key."
  echo "  SSH key: ${NAS_SSH_KEY}"
  [[ -z "${NAS_SSH_ALIAS}" ]] && echo "  Tip: set NAS_SSH_ALIAS=nas in .env to use your ssh config alias"
  exit 1
fi
ok "Connection OK"

ALL_STACKS=(torrentwatch line-secretary homepage jellyfin maid-tracker portainer uptime-kuma watchtower hermes-agent)

# ═══════════════════════════════════════════════════════════════════════════════
# UPLOAD
# ═══════════════════════════════════════════════════════════════════════════════
if [[ "$RESTART_ONLY" == false ]]; then
  echo ""
  printf "${C_BOLD}Source :${C_RESET} %s/\n" "${PROJECT_ROOT}"
  printf "${C_BOLD}Target :${C_RESET} %s:%s\n" "${SSH_DEST}" "${NAS_TARGET_PATH}"
  echo ""

  if [[ "$DRY_RUN" == true ]]; then
    warn "DRY RUN — no files will be transferred"
    echo ""
  fi

  if [[ "$AUTO_YES" == false && "$DRY_RUN" == false ]]; then
    read -r -p "Upload now? [y/N] " CONFIRM
    [[ ! "${CONFIRM}" =~ ^[Yy]$ ]] && echo "Aborted." && exit 0
    echo ""
  fi

  # macOS ships openrsync (protocol 29) which is incompatible with Synology's
  # GNU rsync (protocol 31). Use tar+ssh instead — proven reliable across all
  # macOS versions and NAS firmware. Files are piped in a single SSH session
  # reusing the mux master established above.
  #
  # All .env files are excluded from the tar because macOS bsdtar treats
  # --exclude='./.env' as a glob that matches .env at ANY depth, not just root.
  # Instead, per-stack .env files are uploaded explicitly after the tar step.
  TAR_EXCLUDES=(
    --exclude='./.git'
    --exclude='.env'
    --exclude='./__pycache__'
    --exclude='./*.pyc'
    --exclude='./*.pyo'
    --exclude='./.DS_Store'
    --exclude='./.notes'
    --exclude='./*.egg-info'
    --exclude='./.venv'
    --exclude='./node_modules'
  )

  if [[ "$DRY_RUN" == true ]]; then
    log "DRY RUN — files that would be uploaded:"
    COPYFILE_DISABLE=1 tar -czf - "${TAR_EXCLUDES[@]}" -C "${PROJECT_ROOT}" . \
      | ssh $SSH_OPTS "${SSH_DEST}" \
        "tar -tzf - 2>/dev/null | grep -v '/$' | head -50"
    warn "Dry run complete — no files were transferred."
  else
    # Files on NAS are root-owned (written by docker/Container Manager).
    # Strategy: pipe tar to a tmp file the SSH user can write, then extract with sudo.
    TMP_TAR="/tmp/nas_deploy_$$.tar.gz"

    log "Uploading project files via tar+ssh ..."
    COPYFILE_DISABLE=1 tar -czf - "${TAR_EXCLUDES[@]}" -C "${PROJECT_ROOT}" . \
      | ssh $SSH_OPTS "${SSH_DEST}" "cat > '${TMP_TAR}'"
    ssh $SSH_OPTS "${SSH_DEST}" \
      "bash -lc \"echo '${NAS_SUDO_PASSWORD}' | sudo -S bash -c 'mkdir -p \\\"${NAS_TARGET_PATH}\\\" && tar -xzf \\\"${TMP_TAR}\\\" -C \\\"${NAS_TARGET_PATH}\\\" --no-same-permissions --no-same-owner 2>/dev/null && rm -f \\\"${TMP_TAR}\\\"'\""

    log "Uploading per-stack .env files ..."
    for stack in "${ALL_STACKS[@]}"; do
      local_env="${PROJECT_ROOT}/${stack}/.env"
      if [[ -f "$local_env" ]]; then
        TMP_ENV="/tmp/nas_env_${stack}_$$"
        ssh $SSH_OPTS "${SSH_DEST}" "cat > '${TMP_ENV}'" < "$local_env"
        ssh $SSH_OPTS "${SSH_DEST}" \
          "bash -lc \"echo '${NAS_SUDO_PASSWORD}' | sudo -S cp '${TMP_ENV}' '${NAS_TARGET_PATH}/${stack}/.env' && rm -f '${TMP_ENV}'\""
        dim "$stack/.env"
      fi
    done
    ok "Upload complete ($(elapsed))"
  fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
# RESTART
# ═══════════════════════════════════════════════════════════════════════════════
if [[ "$UPLOAD_ONLY" == true || "$DRY_RUN" == true ]]; then
  echo ""
  ok "All done ($(elapsed))"
  exit 0
fi

if [[ -z "${NAS_SUDO_PASSWORD}" ]]; then
  echo ""
  warn "NAS_SUDO_PASSWORD not set — skipping restart."
  echo "  Add NAS_SUDO_PASSWORD=your_password to .env to enable auto-restart."
  ok "All done ($(elapsed))"
  exit 0
fi

# ── Determine which stacks to restart ────────────────────────────────────────
STACKS_TO_RESTART=()

if [[ -n "$STACKS_ARG" ]]; then
  if [[ "$STACKS_ARG" == "all" ]]; then
    STACKS_TO_RESTART=("${ALL_STACKS[@]}")
  else
    IFS=',' read -ra _INPUT <<< "$STACKS_ARG"
    for s in "${_INPUT[@]}"; do STACKS_TO_RESTART+=("${s// /}"); done
  fi
else
  echo ""
  printf "${C_BOLD}Available stacks:${C_RESET} %s\n" "${ALL_STACKS[*]}"
  echo ""
  read -r -p "Restart stacks (comma-separated / \"all\" / Enter to skip): " STACKS_INPUT
  STACKS_INPUT="${STACKS_INPUT// /}"
  if [[ -z "$STACKS_INPUT" ]]; then
    echo "No stacks selected."
    ok "All done ($(elapsed))"
    exit 0
  elif [[ "$STACKS_INPUT" == "all" ]]; then
    STACKS_TO_RESTART=("${ALL_STACKS[@]}")
  else
    IFS=',' read -ra _INPUT <<< "$STACKS_INPUT"
    for s in "${_INPUT[@]}"; do STACKS_TO_RESTART+=("${s// /}"); done
  fi
fi

if [[ ${#STACKS_TO_RESTART[@]} -eq 0 ]]; then
  warn "No valid stacks selected."
  ok "All done ($(elapsed))"
  exit 0
fi

echo ""
log "Restarting: ${STACKS_TO_RESTART[*]}"

for stack in "${STACKS_TO_RESTART[@]}"; do
  echo ""
  printf "${C_BOLD}── %s ──${C_RESET}\n" "$stack"
  # Pass the entire command as ONE quoted string so SSH sends it verbatim to the
  # remote shell. Splitting into bash/-l/-c/cmd as separate ssh args causes the
  # remote shell to parse the pipe incorrectly (password never reaches sudo -S).
  # --project-directory makes compose resolve the stack's own .env for both
  # variable interpolation and env_file: .env inside docker-compose.yml.
  ssh $SSH_OPTS "${SSH_DEST}" \
    "bash -lc \"echo '${NAS_SUDO_PASSWORD}' | sudo -S docker compose \
      --project-directory '${NAS_TARGET_PATH}/${stack}' \
      -f '${NAS_TARGET_PATH}/${stack}/docker-compose.yml' \
      up -d --build 2>&1\""
  ok "$stack restarted"
done

echo ""
ok "All done ($(elapsed))"
