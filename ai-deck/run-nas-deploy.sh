#!/usr/bin/env bash
# Installed on the trusted runner host; cwd is the independently fetched checkout.
set -euo pipefail
umask 077
: "${AI_DECK_NAS_DEPLOY_ENV:?absolute operator-owned .env.deploy path required}"
: "${SOPS_AGE_KEY_FILE:?runner-host age key path required}"
: "${AI_DECK_DEPLOY_PYTHON:=python3}"
stack="${1:-ai-deck}"
[[ "$stack" =~ ^[a-z0-9-]+$ ]] || { echo 'Invalid stack'; exit 2; }
root="$(pwd -P)"
[[ -f "$root/scripts/render_env.py" && -f "$root/scripts/deploy.sh" && -d "$root/$stack" ]] || {
  echo 'Expected a repository checkout'; exit 2;
}
# Refuse repository-owned provisioning inputs, including symlinks into checkout.
"$AI_DECK_DEPLOY_PYTHON" - "$root" "$AI_DECK_NAS_DEPLOY_ENV" "$SOPS_AGE_KEY_FILE" <<'PY'
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
for value in sys.argv[2:]:
    path=Path(value)
    if not path.is_absolute() or not path.is_file() or path.resolve().is_relative_to(root):
        raise SystemExit('Credential files must be absolute paths outside the checkout')
    if path.stat().st_mode & 0o077:
        raise SystemExit('Credential files must not allow group/world access')
PY
# Repository deployment output can contain decrypted values. Do not forward it to
# users or durable job logs; only publish a generic phase result.
if ! "$AI_DECK_DEPLOY_PYTHON" scripts/render_env.py --root "$root" --exclude deploy >/dev/null 2>&1; then
  echo 'SOPS environment rendering failed; inspect runner configuration'; exit 1
fi
# Compose receives the immutable job revision and opt-in coding profile.
# Only this adapter enables coding; ordinary document-only deployments stay unchanged.
if [[ "$stack" == ai-deck ]]; then
    printf '\nAI_DECK_BUILD_SHA=%s\nCOMPOSE_PROFILES=coding\n' "$(git rev-parse HEAD)" >> "$root/ai-deck/.env"
fi
# deploy.sh sources this exact location. Replace any repository-controlled file,
# then provision it exclusively from the trusted host, never from repo .env.
rm -f "$root/.env.deploy"
cp "$AI_DECK_NAS_DEPLOY_ENV" "$root/.env.deploy"
chmod 600 "$root/.env.deploy"
if ! bash scripts/deploy.sh --yes --stacks "$stack" >/dev/null 2>&1; then
  echo 'NAS deployment command failed'; exit 1
fi
echo 'NAS deployment command completed; separate health check required'
