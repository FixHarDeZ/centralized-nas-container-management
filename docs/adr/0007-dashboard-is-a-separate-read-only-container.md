# The dashboard is a second, read-only container, not a port on the bot

ADR 0002 said no HTTP surface, and the bot process still keeps that promise:
it is still a single Telegram `getUpdates` long-poll loop, it still publishes
no `ports:`, and nothing about how it decides what to render changed. What
gained an HTTP surface is a different container — `shorts-factory-dashboard`,
built from the same image with a different `command`, sitting behind an nginx
sidecar with basic auth on 5067. ADR 0002 is amended by this decision, not
withdrawn: the reasoning that kept an inbound webhook off the bot itself is
untouched, and this ADR only explains the thing that sits beside it.

Two guards keep the dashboard from drifting into a control panel, and neither
depends on the other. The compose file mounts `/data` `:ro`, so even a bug that
tried to write would hit a read-only filesystem. Independently, the app itself
declares no route with a method other than GET or HEAD — `test_no_route_can_write`
walks every route in `dashboard.app.routes` and asserts exactly that. A future
change that wanted the dashboard to act (retry a render, delete a Manifest,
poke the bot) would have to deliberately remove the read-only mount *and*
add a writing route past a test that says not to. Belt and suspenders, and
each one alone would already have stopped the obvious mistake.

It also carries no credential at all. There is no `env_file` on the service,
which is a stronger claim than the read-only mount: it is not just that the
dashboard cannot write, it is that the Telegram bot token and the YouTube
refresh token are physically absent from the one process reachable from the
LAN. Nothing an attacker could extract from this container lets them act as
the bot or upload as the channel — there is nothing to extract. The one file
it reads for its own purposes, `/data/say.json`, is read directly through a
small local `_say()` helper in `app/dashboard.py`, not through `app.render` —
that module pulls in Pillow and edge-tts, and keeping both out of the
LAN-facing process is the point, not an accident of code reuse.

The dashboard shares the bot's image on purpose. It imports `app.manifest`,
`app.experiment`, and `app.analytics` — the same modules the bot itself calls
to write and read a Clip's numbers — rather than re-deriving day-7 views,
gate status, or experiment arms from the raw JSON a second time. Two
implementations of "what counts as day 7" would eventually disagree, and the
failure mode is a browser and a phone quoting different numbers for the same
clip with no way to tell which one is stale.

It does not run under `uvicorn` inside `main.py`, and that is a property of
the bot's own shape rather than a dashboard decision. The bot's poll loop is
inline — a `getUpdates` call blocks the same coroutine that would have to
serve an HTTP request — and rendering a Card means Pillow drawing text and
compositing footage in-process, which is CPU work with no `await` points for
a request to interleave with. An HTTP server sharing that process would hang
for the length of a whole render, which for this bot is minutes, not
milliseconds. A second container sidesteps the question entirely instead of
answering it.

What stays in Telegram stays there: reviewing a Script, pressing render,
`/say` corrections, the upload button. The dashboard reads what has already
happened — the clip list, a Manifest's drafts and render detail, the
experiment's two arms, `state.json` and `say.json` — and decides nothing. The
human still makes every call from the phone; the browser just makes it easier
to see what has already been decided.
