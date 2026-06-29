# Domain Glossary

Shared vocabulary for this repo's architecture. Architecture terms (module,
interface, depth, seam, adapter, leverage, locality) come from the
`codebase-design` skill; the terms below name *this project's* concepts.

## Notifier

The deep module that broadcasts a text message to one or more chat channels.
Small interface, transport hidden:

```
Notifier(line=LineCreds(token, to),
         telegram=TgCreds(token, chat, parse_mode="HTML"|None),
         post=<transport>)          # post injected for tests; default = urllib
    .send(text) -> list[str]         # channels that succeeded, e.g. ["line","telegram"]
```

- **Single source:** `shared/notify.py` (stdlib `urllib` only — no `requests`/`httpx` dependency).
- **Distribution:** vendored into each stack dir by `make sync-shared`; copies are
  committed and guarded by a hash-equality test (build contexts are per-stack, so
  the file must physically exist inside each image's context).
- **Never raises.** A notify failure must not crash a poller. Per-channel errors
  are caught and logged; the failed channel is omitted from the return list.
- **Config stays at the stack.** Each stack reads its own env (key names and
  user-vs-group logic differ per stack) and constructs the creds — the Notifier
  does not read the environment.
- **Sync.** Async callers (torrentwatch) wrap with `asyncio.to_thread(n.send, text)`.

Scope v1: news-feed, torrentwatch, watchtower. **maid-tracker is
excluded** — it pushes to a LINE *group* and sends multi-message image payloads
(signed slip URLs), which would leak LINE's payload shape into the interface.

## channel adapter

A concrete transport satisfying one channel behind the [[Notifier]]: the **LINE
adapter** (`/v2/bot/message/push`) and the **Telegram adapter**
(`/bot<token>/sendMessage`). Two adapters justify the seam. Message *formatting*
is not part of an adapter — it stays local to each stack (good locality).
