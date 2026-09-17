# What claude-desk can take from the Relay build spec

Source: `.refinventory/.claude-desk/relay-ai-workspace-build-spec-v1.md` (Relay v1.0, 2026-09-08).
Status: proposal, nothing implemented. 2026-09-17.

Relay is a multi-tenant Next.js/Postgres SaaS. claude-desk is a single-user stdlib
container behind basic auth. So most of the spec is not applicable — what transfers is
the **streaming-render contract (§11)**, the **SSE resume protocol (§10/§14)** and parts
of the **visual/a11y direction (§4.4/§4.5)**.

## A. Take — ranked

### A1. Stop re-parsing the whole message on every delta — `ui/app.js:1173-1174` (§11, §13.5)

```js
bubble.dataset.raw += ev.text;
markdown(bubble, bubble.dataset.raw);   // clears + rebuilds the entire bubble, per delta
```

Every token throws away and rebuilds all DOM of the answer so far. Cost is O(n²) over a
turn; on a phone a long Thai answer is the worst case. §11 forbids exactly this and §13.5
requires a test that *fails* when an implementation does it.

Server side is already correct: `chat.py:374` emits `text_delta` only, never the
accumulated buffer (§10 delta-only — already satisfied).

Fix shape (keeps the current parser, adds no dependency):
- while streaming, append a text node to the **tail paragraph** only; completed paragraphs
  are never touched again (§4.4 "plain text segmented ตาม paragraph")
- run the existing `markdown()` **once** on `say_end`
- coalesce deltas into one `requestAnimationFrame` commit per frame

Do **not** swap in a markdown library: the current parser is `textContent`-based,
XSS-safe by construction, zero-dep. The defect is *when* it runs, not *what* it is.

### A2. Scroll reads on every delta — `ui/app.js:1039-1046` (§11)

`atBottom()` reads `scrollHeight`/`clientHeight` and `follow()` writes `scrollTop`, once
per delta — a forced layout per token, next to A1. §11 prescribes a bottom sentinel +
`IntersectionObserver` for pinned state, and one scroll per rAF. Same rAF as A1.

### A3. SSE resume after a drop (§10, §14)

`chat/events` has no `id:`/sequence, and the page has no gap handling — `EventSource`
reconnects on its own and picks up mid-stream, so the bubble silently loses whatever
arrived while it was away. This is not an edge case here: **iOS suspends a backgrounded
PWA's JS**, which is already why the done-hook notification does not fire on a locked
screen — reconnect is the normal path on a phone.

Minimal version of §10's protocol:
- `id: <seq>` per event, client ignores `seq <= lastApplied`
- on reconnect, `Last-Event-ID` / `?after=` replays from a bounded ring
- if the ring has rolled past, repaint from `GET /chat/history` — the endpoint and the
  `session_id` in `/chat/state` already exist, only the client half is missing

### A4. Composer draft survives a reload (§11 state ownership, §14 offline)

Typed text is lost on reload / tab eviction. Debounced `localStorage`, keyed by
`session_id`. Small, phone-shaped.

### A5. "Jump to latest" button (§4.4)

`follow()` correctly refuses to yank the view when the reader scrolled up — but nothing
offers a way back down. A pill above the composer, shown only when not at bottom.

### A6. Tool pills say state with colour alone — `ui/style.css:369-371` (§4.5)

`.pill.ok/.bad` change only `.p-dot`'s colour. Add a glyph (✓ / ✕ shaped as SVG).

### A7. No `:focus-visible`, no `prefers-reduced-motion` anywhere in `ui/style.css` (§4.5)

Grep returns zero hits for both. The typing dots and every `--t` transition ignore the
reduced-motion preference; keyboard focus on the desk (used from a laptop too) is
whatever the UA draws. Cheap, mechanical.

### A8. Error text is a bare Thai string — `ui/app.js:1203-1206` (§4.4, §10 error shape)

`'ทำงานไม่สำเร็จ'` with no cause and no retry affordance. §4.4 wants a disclosable cause
plus a `ลองใหม่` action. Worth at least a stable code from `chat.py` so the page can say
*which* failure.

## B. Considered, rejected

**Whole stack, on the 2 GB single-container constraint** — Next.js, React, Tailwind,
shadcn/ui, TanStack Query, Zod, pnpm, Vercel AI SDK, Drizzle, Better Auth, Postgres,
S3/MinIO, pgvector. The UI is vendored xterm.js with no bundler; `chat.py`, `upload.py`,
`ask.py` are stdlib-only by decision. Any of these means a build step and a runtime
dependency inside a container already holding Claude Code + LibreOffice.

**Multi-tenancy in every form** — workspaces, membership roles, cross-workspace threat
tests, RLS, audit events, share links, presigned uploads, rate limits. One user behind
nginx basic auth; `/work` is the tenant.

**Runs as first-class persisted objects** — run table, `clientRequestId` idempotency,
retry/regenerate branches, startup stale-run sweep. Claude Code owns the transcript
(`~/.claude/projects/*.jsonl`); duplicating it into a store the desk maintains is the
thing ADR 0013 chose not to do.

**Model picker / profiles / context meter / usage-cost budgets** — the agent picks its
own model; `total_cost_usd` is already surfaced per turn and per session.

**Lucide icons, no emoji structural icons (§0)** — header buttons are already inline SVG.
The rule points at the key bar (`⧉ ⎘ ↵ ^C A− A+`), but those glyphs *are* the physical
keys they send; an SVG makes them less recognisable, not more. Keep.

**Performance harness (§13)** — Playwright + CPU-throttled fixtures + committed baselines
is a heavier apparatus than the thing it measures. The one rule worth keeping is the
assertion behind `stream-thai`: a test that fails if markdown is parsed per delta. That
belongs in `claude-desk/tests/` against the fake agent, not a perf suite.

## C. Suggested order

A1 + A2 together (one rAF commit, one code path), then A3, then A5/A6/A7 as a UI polish
pass, then A4, then A8.
