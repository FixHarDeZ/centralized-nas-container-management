"""Send the Claude sign-in link to Telegram when the page's login button runs.

On a phone the link in the terminal is hard to get at. This module watches the
desk's tmux pane after `/api/login` types `claude auth login`. When an OAuth
link shows up, it posts the link to an n8n webhook, and n8n's Secretary Bot
sends it to the owner's Telegram chat.

The bot token never enters this container. Claude runs here with
--dangerously-skip-permissions, so the agent can read anything in its env.
This process holds only DESK_LOGIN_TOKEN, and the n8n workflow accepts that
token for one purpose: relaying a URL that passes the same allowlist again.

The Telegram message only delivers the link. The code from claude.ai still
gets pasted back into the deck (⎘ Paste). Nothing from Telegram is typed into
a pane.

Off unless DESK_LOGIN_WEBHOOK and DESK_LOGIN_TOKEN are both set. Fires only
for the desks listed in DESK_LOGIN_NOTIFY (basic auth users), so another
person's sign-in link never lands in the owner's chat.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import parse_qs, urlsplit

# Keep these rules identical to findClaudeLoginURL in ui/app.js.
# tests/test_login_link.py runs the same cases as tests/claude_login_harness.html.
HOSTS = {"claude.com", "claude.ai", "console.anthropic.com", "platform.claude.com"}
PATH = re.compile(r"^(/[a-z]+)?/oauth/authorize$")
SHORT_QUERY = re.compile(r"^z-[A-Za-z0-9_-]{16,}$")   # Claude Code 2.1.330+
CANDIDATE = re.compile(r"https://\S+")

WATCH_SECONDS = 20     # `claude auth login` prints the link within ~1 s
POLL_SECONDS = 0.5
SEND_TIMEOUT = 10


def is_login_url(raw: str) -> bool:
    try:
        url = urlsplit(raw)
        port = url.port
    except ValueError:
        return False
    if url.scheme != "https" or url.username or url.password or port:
        return False
    if url.hostname not in HOSTS or url.netloc != url.hostname:
        return False
    if not PATH.match(url.path):
        return False
    if SHORT_QUERY.match(url.query):
        return True
    params = parse_qs(url.query)
    return all(k in params for k in ("client_id", "state", "code_challenge"))


def find_login_urls(text: str) -> list:
    """Every Claude sign-in link in the text, in order of appearance."""
    return [m for m in CANDIDATE.findall(text) if is_login_url(m)]


def _screen(target: str) -> str:
    # -J joins soft-wrapped rows, so a link wider than the pane comes back whole.
    try:
        done = subprocess.run(
            ["tmux", "capture-pane", "-p", "-J", "-t", target, "-S", "-200"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def config(env=None):
    """(webhook, token, notify users) or None when the feature is off."""
    env = os.environ if env is None else env
    webhook = env.get("DESK_LOGIN_WEBHOOK", "").strip()
    token = env.get("DESK_LOGIN_TOKEN", "").strip()
    users = [u.strip().lower() for u in env.get("DESK_LOGIN_NOTIFY", "").split(",") if u.strip()]
    if not webhook or not token or not users:
        return None
    return webhook, token, users


def send(webhook: str, token: str, url: str, desk: str) -> bool:
    body = json.dumps({"url": url, "desk": desk}).encode()
    req = urllib.request.Request(
        webhook, data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Desk-Token": token},
    )
    try:
        with urllib.request.urlopen(req, timeout=SEND_TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except OSError as exc:
        print(f"login_link: send failed: {exc}", file=sys.stderr, flush=True)
        return False


def watch(target: str, desk: str, before: set, cfg, screen=_screen,
          sender=send, seconds=WATCH_SECONDS, poll=POLL_SECONDS) -> str:
    """Wait for a sign-in link that was not on screen before; send it once.

    Returns the URL that was sent, or "" when none appeared in time.
    """
    webhook, token, _ = cfg
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        fresh = [u for u in find_login_urls(screen(target)) if u not in before]
        if fresh:
            url = fresh[-1]
            return url if sender(webhook, token, url, desk) else ""
        time.sleep(poll)
    return ""


def start(target: str, desk: str, wanted_targets: set, before: set, cfg) -> bool:
    """Watch in the background if this desk is one that should notify."""
    if cfg is None or target not in wanted_targets:
        return False
    threading.Thread(
        target=watch, args=(target, desk, before, cfg), daemon=True,
        name="login-link",
    ).start()
    return True
