#!/usr/bin/env python3
"""`ask <question>` — one question to the mimo endpoint, one answer on stdout.

This is deliberately *not* an agent — `mimo` (MiMoCode) is the agent on this
desk, which is also why this command is called `ask` and not `mimo`. No tools,
no file access, no loop: one question, one answer, seconds rather than the ~28s
a tool-using turn costs. For the small things (summarise, rewrite, explain an
error) that need neither an agent nor subscription quota.

  ask "แปลเป็นอังกฤษ: ..."       question in the arguments
  cat out/notes.md | ask "สรุป"   stdin becomes the material
  ask < prompt.txt                stdin alone is the question

Rules carried over from shared/mimo.py, each bought with an incident there:
no `max_tokens` (the reasoning budget is spent first and the reply comes back
empty) and `reasoning_effort=low` (the default burned 3x the tokens for a
worse answer). The timeout here is urllib's, which is per socket operation,
not the wall-clock deadline the bots wrap their calls in: a server that
trickles bytes could outlast it. That rule exists so a bot's poll loop never
freezes; this is a foreground command with a human and a Ctrl+C on the other
end, so the weaker bound is the one it gets.

Not streaming on purpose: the same answer measured 400s streamed against 137s
in one shot. The waiting counter on stderr is what the phone gets instead.
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

DEFAULT_MODEL = "mimo-v2.5-pro"
DEFAULT_BUDGET = 300.0
USAGE = """ask — ถามคำถามเดียว ตอบครั้งเดียว (ไม่ใช่ agent, ไม่แตะไฟล์ — agent คือ `m`)

  ask "แปลเป็นอังกฤษ: ..."
  cat out/notes.md | ask "สรุปสั้นๆ"
  ask < prompt.txt
"""


def read_prompt(argv: list[str]) -> str:
    """Arguments, stdin, or both — the ask first, the piped material after."""
    ask = " ".join(argv).strip()
    piped = "" if sys.stdin.isatty() else sys.stdin.read().strip()
    if ask and piped:
        return f"{ask}\n\n---\n{piped}"
    return ask or piped


def ticker(stop: threading.Event) -> None:
    """A counter on stderr: a minute of silence on a phone reads as a hang.
    stderr so `ask ... > file` and pipes still get only the answer."""
    start = time.monotonic()
    while not stop.wait(1.0):
        sys.stderr.write(f"\r\033[38;5;245m  ask … {time.monotonic() - start:.0f}s\033[0m")
        sys.stderr.flush()
    sys.stderr.write("\r\033[K")
    sys.stderr.flush()


def ask(prompt: str) -> str:
    key = os.environ.get("MIMO_API_KEY")
    if not key:
        raise SystemExit("ask: MIMO_API_KEY is not set (check the stack's .env)")
    base = os.environ.get("MIMO_BASE_URL", "").rstrip("/")
    if not base:
        raise SystemExit("ask: MIMO_BASE_URL is not set (check the stack's .env)")

    body = {
        "model": os.environ.get("MIMO_MODEL", DEFAULT_MODEL),
        "messages": [{"role": "user", "content": prompt}],
        "reasoning_effort": os.environ.get("MIMO_REASONING_EFFORT", "low"),
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    budget = float(os.environ.get("MIMO_ASK_TIMEOUT_SECONDS", DEFAULT_BUDGET))
    with urllib.request.urlopen(req, timeout=budget) as resp:
        payload = json.load(resp)
    choice = payload["choices"][0]
    text = (choice.get("message") or {}).get("content") or ""
    if not text.strip():
        raise SystemExit(f"ask: empty reply (finish_reason={choice.get('finish_reason')})")
    return text.strip()


def main() -> int:
    prompt = read_prompt(sys.argv[1:])
    if not prompt:
        sys.stderr.write(USAGE)
        return 2

    stop = threading.Event()
    spinner = threading.Thread(target=ticker, args=(stop,), daemon=True)
    if sys.stderr.isatty():
        spinner.start()
    try:
        answer = ask(prompt)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise SystemExit(f"ask: HTTP {exc.code} — {detail}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # A stall is a window, not a request (shared/mimo.py): hedging never
        # rescued one. Say so instead of retrying into the same sick minute.
        raise SystemExit(f"ask: no answer ({exc}) — the endpoint stalls in windows, try again in a few minutes")
    finally:
        stop.set()
        if spinner.is_alive():
            spinner.join(timeout=2)

    print(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
