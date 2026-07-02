#!/bin/sh
# Inject dashboard.basic_auth into config.yaml before starting dashboard
# Reads from DASHBOARD_BASIC_AUTH_USER and DASHBOARD_PASSWORD_HASH env vars

CONFIG_FILE="${HERMES_HOME:-/opt/data}/config.yaml"

if [ -z "$DASHBOARD_PASSWORD_HASH" ]; then
    echo "[inject-auth] DASHBOARD_PASSWORD_HASH not set, skipping auth injection"
    exec "$@"
fi

AUTH_USER="${DASHBOARD_BASIC_AUTH_USER:-fixhardez}"

# Check if dashboard.basic_auth already exists
if grep -q "^dashboard:" "$CONFIG_FILE" 2>/dev/null && \
   grep -A5 "^dashboard:" "$CONFIG_FILE" | grep -q "basic_auth:"; then
    echo "[inject-auth] dashboard.basic_auth already exists in config.yaml, skipping"
    exec "$@"
fi

echo "[inject-auth] Injecting dashboard.basic_auth into config.yaml"

# Append dashboard auth config
cat >> "$CONFIG_FILE" << EOF

dashboard:
  basic_auth:
    username: ${AUTH_USER}
    password_hash: "${DASHBOARD_PASSWORD_HASH}"
EOF

echo "[inject-auth] Done. Starting dashboard..."
exec "$@"
