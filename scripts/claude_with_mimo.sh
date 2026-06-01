#!/usr/bin/env bash

# Run Claude Code with MIMO proxy.
# Secrets come from the sops vault via: make secrets --stack scripts
# Requires ANTHROPIC_API_KEY in vault at shared.mimo.anthropic_api_key

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: $ENV_FILE not found."
  echo "Run 'make secrets --stack scripts' to generate it from the vault."
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

cd "$SCRIPT_DIR/.." && claude --model mimo-v2.5-pro