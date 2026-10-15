# Shop Flow Studio Implementation Plan

> Execute using subagent-driven-development, task reviews and final review. Worktree `/private/tmp/shorts-flow-studio`; base `ec2eb27`. User approved implementation.

**Goal:** Creator Studio Shop jobs, manual Google Flow import, video rendering, n8n dispatch and Telegram milestones.
**Architecture:** Dedicated FastAPI Shop API, SQLite durable jobs and commands, worker, Jinja/vanilla JS UI under existing authenticated nginx.
**Stack:** Existing Python/FastAPI/FFmpeg/Pillow/TTS, SQLite, Docker Compose, n8n.

## Global constraints
- Target 25–40 seconds, 3–6 scenes plus end card; measured TTS timing; at least one approved video.
- Manual Flow only. No paid generation API or browser automation. User confirms reference match; text model does not see images.
- Preserve legacy /shop, Shorts records, and dashboard read-only bot mount/no drawing imports.
- Immutable render snapshots, optimistic revisions, duplicate-command protection, expiring claims, atomic output.
- Video 100 MiB / 60 sec / max 3840x2160 or portrait; photos 15 MiB / maximum 6. Decode in worker.
- Missing/short video blocks render; no silent looping/freezing. Strip source audio. Crop/contain selectable.
- Authenticated media, CSRF/same-origin browser writes, scoped automation credential. No secrets in logs.
- No live deployment before verification. Synthetic test clip validates mechanics, not real product fidelity.

## Task 1: Durable domain and API
Files: `app/shop_store.py`, `app/shop_api.py`, `tests/test_shop_store.py`, `tests/test_shop_api.py` in shorts-factory.
Interfaces: `Store(root: Path)` owns root/shop.sqlite3 and root/assets. API factory `create_app(root: Path | None = None)`. JSON-serializable records; document exact signatures in report for worker/UI.

- [ ] Write failing tests for reopen persistence, stale edit, immutable snapshot, repeated render, scene acceptance, lease recovery and stale completion. Example sequence: update product at revision 1; update again at revision 1 raises Conflict; reopen retains first update.
- [ ] Implement transactional store: product fields name/brief/destination/prices/link/references; plan uses existing Pitch plus per-beat id/source(flow,real,still)/prompt/reference/fit/media/accepted; commands, renders, deduplicated outbox.
- [ ] API/store must not import rendering/shop modules. Worker validates model/user plans using existing Pitch validator.
- [ ] Stream generated-name uploads to store; limits, ownership checks; pending probe command before usable. Type/extension alone never implies valid.
- [ ] REST `/shop/api/jobs` create/list, `/{id}` read/edit, references, plan request/save/approve, scene upload/accept, prompt pack, render request/status/approval, asset downloads. Require current revision for state changes.
- [ ] CSRF cookie/header comparison + same-origin validation for browser mutations. nginx supplies Basic Auth. Automation `/shop/automation/...`: constant-time token validation, disabled without token; pending render list, idempotent start matching revision, status, milestone notification commands.
- [ ] Render request persists pending dispatch. n8n start queues work. Duplicate snapshot returns existing active/successful render. Explicit failed retry creates attempt, never parallel execution.
- [ ] Test auth/CSRF, stale approvals, upload/traversal/ownership, dispatch idempotency. Use local repo venv with PYTHONPATH=shorts-factory.
- [ ] Report callable contracts/tests/concerns; parent commits integration.

## Task 2: Worker and video renderer
Files: new `app/shop_worker.py`, `app/shop_media.py`, `app/render_lock.py`, `tests/test_shop_worker.py`, `tests/test_shop_media.py`; modify `app/shop_render.py`, `app/main.py` lock/help only.
Interfaces: consume Task 1 store. Preserve `shop_render.build` API; optional per-beat video/fit. Async `render_lock.acquire()` flock on shared output path.

- [ ] First test invalid/short media, actual generated video/audio removal, crop/contain dimensions and lease ownership.
- [ ] Bounded ffprobe/decode with size/dimension/duration/type validation; image decompression safety. Worker claims commands, heartbeat off expensive event-loop work, unique attempt temp paths, recovery, stale completion rejection.
- [ ] Use existing shop.generate/validate; enrich each scene with explicit English Flow prompt using factual brief, narration, movement/settings and consistent product guardrails. User confirms reference. Edited plans validated before approval. Safe prompt/reference ZIP for approved current revision.
- [ ] Render frozen snapshots under shared flock; TTS measured durations first. Trim long video, reject short with scene-specific error, strip original audio, crop/contain, deterministic text/end card. Bound ffmpeg and max 2 encoding threads.
- [ ] Atomic final MP4/caption/details, only lease owner completes. Retry preserves snapshot. Telegram send via existing interface; deduplicated milestones, bounded backoff; notification failure never fails render.
- [ ] Wrap both legacy render entry points with same lock; Flow waiting takes no lock. /shop help links workspace if configured.
- [ ] Run focused worker/media/legacy Shop tests, report contracts/results.

## Task 3: Creator Studio UI
Files: new `templates/shop_list.html`, `templates/shop_job.html`, `static/shop.js`, `static/shop.css`, `tests/test_shop_studio.py`; modify `templates/base.html`, `shop_api.py` HTML routes only.
Interfaces: Task 1 REST. HTML /shop and /shop/{id}; base shell/static served by dashboard. Preserve current revision in forms.

- [ ] Test empty/list/detail/escaping/statuses and no drawing import boundary.
- [ ] Shop navigation, filters, create/edit all product fields, reference upload/preview. Reuse dark/light responsive shell.
- [ ] Generate and edit plan/scenes, save/approve, confirm reference, copy prompt, download reference/ZIP and external Flow link.
- [ ] Individual upload/replace/preview/accept; validation error/progress; fit selector; required scenes; render/retry/final approval/download/caption.
- [ ] Old render explicitly outdated after edits. Poll pending state without discarding unsaved edits. CSRF and conflict handling; no untrusted innerHTML. Keyboard/touch accessible, 320–1440px.
- [ ] Focused UI/API tests and browser inspection; report results.

## Task 4: Wiring, orchestration and validation
Files: shorts-factory Compose/nginx/README/secrets manifest; root docs env; both stack memories; `n8n/workflows/Shop_Flow_Studio.json`, setup docs, integration tests.

- [ ] Shop API/worker same image, dedicated store volume, output mount, worker-only needed credentials. Keep dashboard read-only. nginx /shop with Basic Auth and upload overhead cap; port 5071 unchanged. Automation adds scoped token.
- [ ] Add token using vault workflow, sync test vault, render env without revealing values. Document n8n credential setup, no embedded secrets.
- [ ] Inactive n8n workflow: schedule/reconcile -> list pending and monitoring -> start by ID/revision -> wait/check -> milestone. Bound retries/polling, next schedule resumes. IDs/status only, no media binaries. Validate node schema against official docs.
- [ ] Local focused tests, Docker font/Raqm full suite, lint; synthetic end-to-end clip through upload/probe/plan approval/dispatch/render/download/restart. Browser desktop/mobile/light/dark, authentication gates.
- [ ] Whole-change review, fix important findings, update ADR/docs/memory with actual evidence and live integration limitations; local commit no co-author. Real Flow acceptance and NAS deployment cannot be claimed from synthetic/local tests.
