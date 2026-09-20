#!/usr/bin/env bash
# Run against a disposable image, without provider credentials or host volumes:
# docker run --rm -i --network none --entrypoint /bin/bash IMAGE -s < tests/container_smoke.sh
set -euo pipefail
codex --version
command claude --version
/usr/local/bin/entrypoint.sh >/tmp/desk-startup.log 2>&1 &
desk_pid=$!
trap 'cat /tmp/desk-startup.log; kill "$desk_pid" 2>/dev/null || true' EXIT
ready=false
for attempt in $(seq 1 20); do
    if curl -fsS 'http://127.0.0.1:7683/chat/state?provider=codex' >/tmp/state.json 2>/dev/null; then
        ready=true
        break
    fi
    kill -0 "$desk_pid" || break
    sleep 1
done
[[ "$ready" == true ]]
python3 -c 'import json; d=json.load(open("/tmp/state.json")); assert d["busy"] is False; print("Codex chat state OK")'
curl -fsS 'http://127.0.0.1:7682/api/sessions?provider=codex'
test -f "$HOME/.agents/skills/pptx/SKILL.md"
test -f "$HOME/.agents/skills/docx/SKILL.md"
cmp /work/AGENTS.md /work/CLAUDE.md
python3 -c 'import sys; sys.path.insert(0,"/opt/ai-deck"); import chat; assert chat.agent_for("alice","codex") is not chat.agent_for("bob","codex"); print("Skills, work instructions and user routing OK")'
python3 - <<'PY'
import sys, time, json, urllib.request
sys.path.insert(0, '/opt/ai-deck')
import chat
chat.Agent()._translate({'type': 'rate_limit_event', 'rate_limit_info': {
    'status': 'allowed', 'unifiedWindows': {
        'five_hour': {'utilization': .27, 'resetsAt': time.time() + 3600},
        'seven_day': {'utilization': .52, 'resetsAt': time.time() + 90000}}}})
def status(provider):
    return json.load(urllib.request.urlopen('http://127.0.0.1:7682/api/status?provider=' + provider, timeout=12))
claude = status('claude')
assert claude['five_hour']['pct'] == 27 and claude['seven_day']['pct'] == 52
codex = status('codex')
assert codex['provider'] == 'codex' and codex['status'] == 'unavailable'
assert 'five_hour' not in codex and 'done' not in codex
print('Chat quota persistence, API routing and credential-free Codex fallback OK')
PY
