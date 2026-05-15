# line-secretary — Stack Index

LINE Messaging API bot backed by Notion. Receives webhooks, uses LLM (Groq/OpenRouter) to read and write Notion pages/databases.

## Ports
| Internal | External (Synology RP) |
|---|---|
| 5057 | 5058 (HTTPS) |

## Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app — webhook handler, `/debug*`, `/clear`, `/provider`, `/help` commands |
| `agent.py` | LLM agent — Notion search, proposal parsing, write execution |
| `notion.py` | Notion API client — search, read pages/tables, CRUD |
| `cache.py` | In-memory page/header cache, background rebuild every 10 min |
| `provider.py` | AI provider selection — Groq primary, OpenRouter fallback |
| `store.py` | Persistent state — pending writes, pending_general, conversation history |
| `line_client.py` | LINE API — signature verify, push message |
| `config.py` | Pydantic settings from env |

## AI Providers
- **Auto mode** (both keys set): Groq primary → OpenRouter failover on rate-limit
- **Single mode**: whichever key is set (`AI_PROVIDER` env)
- Models: `llama-3.3-70b-versatile` (main) / `llama-3.1-8b-instant` (small queries)

## Write Flow
1. User message → `agent.run()` → LLM proposes JSON action
2. Bot replies with confirm prompt
3. User replies "ใช่" → `execute_write()` → Notion API
4. Supports: add/update/delete table rows, add/update/delete database rows (batch)

## State (`/data/state.json`)
- `pending`: write proposals awaiting user confirmation
- `pending_general`: general-knowledge questions awaiting confirmation
- `history`: last 4 exchanges per user (for LLM context)

## Cache
- `list_all_pages`: pages TTL 5 min
- `get_page_headers`: per-page TTL 10 min
- Background rebuild every 10 min at startup

## Recent Changes
- **2026-05-15**: code cleanup — removed dead `location` variable in `agent.py`, hoisted `notion` import to top-level in `main.py`, fixed extra blank line in `notion.py`
- **2026-05-15**: maid-tracker code cleanup — removed dead vars (`_AUTH_REALM`, 9 keyword aliases, unused `daily_rate` import), eliminated 3× inline `ZoneInfo()` with module-level `_TZ`, removed duplicate employee DB fetch in `upsert_attendance`, refactored `toggle_payment` to use `_compute_period_amount`, fixed local imports (`Response`, `calendar`) in middleware/webhook/calc
- **2026-05-15**: torrentwatch v2.17.0 — dynamic category names: `_cat_cache` (pre-seeded, overwritten by live HTML alt/title), `GET /api/categories` endpoint, `upsert_torrent` UPDATE now refreshes `category` field, frontend uses `catLabel()` helper for chips + badges
