# shorts-factory is Telegram-only: no HTTP server, no nginx, no published port

Every other stack in this repo publishes a port behind an nginx sidecar with
basic auth from the vault. shorts-factory deliberately does not: its whole
interaction loop (send a topic, read the generated script, press a button,
receive the clip) fits in a Telegram chat, and it has no inbound webhook, so
nothing needs to listen. (It had no scheduler either when this was written;
ADR 0004 added a daily job that pulls performance snapshots. That job makes
outbound calls only and does not change this decision.) The container runs a single
`getUpdates` long-poll loop with no FastAPI, no uvicorn, and no
`ports:` mapping. That deletes an nginx sidecar, an `.htpasswd`, a vault entry,
and a LAN-reachable attack surface. The remaining trust boundary is the bot
itself: inbound updates are accepted only from the configured chat_id and
anything else is dropped, the same guard torrentwatch applies to its callbacks.
Without it, any stranger who finds the bot can spend LLM credit and start
renders on the NAS. A future dashboard would have to add the nginx layer back.

**Amended 2026-09-01 by `docs/adr/0007`:** the dashboard was built. The bot
process is still portless and Telegram-only; the HTTP surface belongs to a
separate read-only container behind nginx basic auth on 5067.
