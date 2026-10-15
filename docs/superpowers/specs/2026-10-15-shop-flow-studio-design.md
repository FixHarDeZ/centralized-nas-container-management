# Shop Flow Studio

Date: 2026-10-15. Status: proposed detailed design; user selected semi-automatic Google Flow and Creator Studio UI. Detailed specification awaits review.

## Outcome

Create product clips with actual moving scenes. The user supplies product facts and references, reviews a shot plan, generates selected scenes manually in Google Flow, then uploads and approves those scenes in Creator Studio. shorts-factory adds Thai narration, subtitles, music and the final product/price card. n8n coordinates rendering and notifications.

Initial target: 25–40 seconds, vertical 9:16, 3–6 scenes plus an end card. Reuse existing output dimensions and Thai rendering. At least one approved video scene is required for the new workflow. Do not silently substitute zooming photos for missing videos.

## User workflow

1. Open Shop in Creator Studio. Create a product with name, factual brief, optional current/old price, affiliate link and destination platform (Shopee Video, Facebook or YouTube). Upload 1–6 reference photos. Facts and photos remain editable in draft.
2. Generate a shot plan: Thai narration, on-screen text, scene purpose, reference photo, source type, and an English Flow prompt describing action, setting, framing and product consistency. Source types: Flow video, user-supplied real video, or still detail. User assigns or confirms the reference photo; a text-only model must not claim to have inspected it.
3. Review and edit the plan. Approval freezes a revision and exposes a downloadable prompt/reference pack. Each scene has Copy prompt and Download reference actions. Opening Flow is an external link; it neither authenticates nor submits a generation.
4. Generate scenes manually in the user's own Flow account. Upload results to the matching scene card. Each card shows requested action, reference, clip preview and validation results. User can replace or accept a clip independently.
5. When every required scene is accepted, choose Render. n8n requests rendering of that exact approved revision. Show queued/running/failed/ready states in Shop.
6. Review the final clip, download MP4 and copy caption. Changing a scene or script invalidates the final approval and creates a new render revision. Publishing and product tagging remain manual.

Telegram announces actionable milestones and links back to the job. No per-scene chat conversation is required. The existing /shop photo workflow remains available during rollout; the new workspace does not use its single holding state. Add a link to the new workspace in /shop help.

## Screens

- Shop list: product thumbnail, name, updated time, status, completed/required scenes, and New product. Filters: drafts, waiting for clips, ready to render, rendering, finished, failed. Clear empty and failed states.
- Product workspace: brief and references; editable script/shot plan; scene cards; final render and caption. Show a plain next-action message above the current stage.
- Scene card: purpose and narration, selected reference, copyable Flow prompt, source selection, upload/replace, inline video preview, Accept scene. Rejected or missing media must be visible without opening logs.
- Follow Creator Studio's existing dark/light styling, keyboard focus, mobile layout and accessible labels. Prompts can expand; operational IDs and workflow details stay out of the primary user flow.

## Boundaries and ownership

- Existing dashboard supplies navigation and the authenticated site shell. Keep its existing bot data mount read-only and preserve the no-PIL/no-edge_tts dashboard boundary.
- Add a Shop API service and a Shop worker to the existing shorts-factory Compose stack. Shop API owns persistent records, uploads, media serving and durable command/outbox creation. Worker owns model calls, media probing, narration and rendering. Both use the existing image with separate entry points.
- Persist Shop metadata in a dedicated SQLite database on a local Docker volume. Store immutable media versions and exported clips under a dedicated Shop subtree of the existing output storage. Neither service writes the legacy bot state or experiment history.
- n8n orchestrates approved jobs over HTTP. It does not own product records or render media. Restarting or replacing a workflow must not lose the product job.
- New paths are routed by existing nginx, preserving browser authentication. Internal automation endpoints require a separate scoped service credential. Add no unauthenticated public callback exception. Do not share Telegram's polling bot with an n8n Telegram Trigger.

Shop API can enqueue work directly when n8n is temporarily unavailable; retain the render request as pending dispatch and show that status. The worker only starts a queued render after an accepted start command, so dispatch retries cannot start duplicate work. A reconciliation workflow retries pending dispatches.

## Records and concurrency

Product: opaque ID, timestamps, factual brief, destination, prices, affiliate link and reference assets.

Plan revision: product ID, version, script, scenes, selected references and approval timestamp. Scene: ID, source type, narration, subtitle lines, Flow prompt, required duration, media version and acceptance timestamp.

Render: ID, immutable plan/media snapshot, status, attempt count, timestamps, error, final assets and approval timestamp. Asset: generated storage key, original display name, type, size, hash, dimensions, duration and validation outcome.

Commands and outbox events have unique IDs and retry state. Use transactions and expected revision checks to reject stale edits. Duplicate render requests for the same snapshot return the existing active/successful render. Explicit retry of a failed render creates a new attempt, not a parallel task.

Worker claims use expiring leases and heartbeat timestamps. Restart recovers queued work and marks interrupted render attempts retryable. Temporary outputs are never shown as finished; final output publication is atomic. Serialize Shop rendering and legacy rendering with a shared process-safe render lock. Waiting on external Flow assets never takes that lock or blocks trends.

## API contract outline

Browser routes under /shop; JSON endpoints under /shop/api. Support create/read/update product, upload references, request plan generation, edit/approve a plan revision, upload/accept scene media, request a render, read job status and download final assets. Mutations require browser authentication, same-origin checks and CSRF protection.

Automation endpoints: list pending dispatches; start an approved render by render ID and revision with an idempotency key; read render status; request a milestone notification. The notification request is idempotent and executed by a shorts-factory component with the existing Telegram sender, not with credentials exported to the browser.

n8n workflow: scheduled reconciliation -> read pending render requests -> start each render -> wait -> check status -> continue waiting or request ready/failed notification. Bound polling and retries; timed-out monitoring does not imply a failed render. Next reconciliation can recover monitoring from the database. Store only IDs/status in workflow execution data, not video binaries or product reference archives.

## Media and render behavior

- Initial video upload: MP4 or MOV, maximum 100 MiB and 60 seconds per scene. Reference photos: JPEG/PNG/WebP, maximum 15 MiB each. Validate actual decoded contents; extension and Content-Type are not proof. Match nginx limits to API limits with multipart overhead.
- Stream uploads to temporary files; verify with bounded ffprobe/decoder execution in the worker. Reject invalid/unsupported streams, excessive resolution (above 3840x2160 or portrait equivalent), and empty or corrupt files. Originals never execute. Storage paths derive from server IDs, never client filenames.
- Prompt for vertical framing. Preview framing before acceptance; offer crop or contain for nonvertical media. Preserve the original. Strip source audio in the first version; existing Thai narration and music own the final soundtrack.
- After narration synthesis, use measured scene spans as the timing authority. Trim long clips. If a video cannot fill its scene, stop with a scene-specific action: upload a longer clip or shorten narration. Do not silently loop or freeze to fill time. A still scene may fill its planned span.
- Render fixed readable text overlays separately from scene video. Price and affiliate CTA stay in deterministic end-card/caption generation; ask Flow for no generated lettering or prices.
- Prompts request consistent product shape, color and logo but cannot guarantee them. Scene acceptance explicitly asks the user to compare these with the real reference. Use real footage for demonstrations that assert product performance. Do not fabricate testimonials or unsupported product benefits.
- Preserve existing sourced-number and disclosure rules. Destination controls CTA text; do not imply an affiliate URL is automatically a tagged product or clickable on every platform.

## Recovery and errors

Missing scenes block rendering with a list of required actions. Plan/model failure preserves the brief and last good revision. Upload/probe failure preserves the prior accepted media. A narration/render failure preserves accepted scenes and exposes Retry. Editing a rendered job makes its old render visibly outdated rather than overwriting it. Failed Telegram delivery never marks a successful render failed.

API errors distinguish invalid input, stale revision, missing media, busy/queued work and transient provider errors. Logs include job and attempt IDs without credentials. Replaced assets remain available to immutable render snapshots; deletion/retention automation is outside this first release.

## Delivery and validation

Deliver in order: persistent Shop jobs and UI; plan/reference pack and scene upload review; video renderer and final review; n8n dispatch/reconciliation and Telegram milestone integration. Each stage must preserve legacy workflows.

Required verification: restart persistence; concurrent/stale edits; duplicate start requests; failed dispatch recovery; upload/path validation; invalid media and short-video handling; TTS duration alignment; source-audio removal; one render at a time across bot and Shop; authenticated media access; CSRF rejection; desktop/mobile scene editing and upload; n8n retry/restart behavior. Run one end-to-end example using a real user-generated Flow clip and verify final Thai audio, subtitles and product appearance manually.

No automated Flow login, browser generation, paid generation API, Shopee scraping, auto-publishing, multi-user tenancy, affiliate sales attribution or migration into the Shorts experiment pipeline in this version.

Deployment changes include Compose services/volumes, nginx routes/upload limits, a scoped automation secret and an n8n workflow. Update ADR 0015 and dashboard boundary documentation to reflect the new service, plus README and stack memory. Secrets use existing vault/render_env workflow. Deployment uses repository deploy tooling after implementation verification. Current NAS runtime and existing n8n workflows have not been inspected in this design session.

## References

- Existing decision: docs/adr/0015-product-clips-are-a-mode-of-shorts-factory.md
- Google Flow creation: https://support.google.com/flow/answer/16353334
- Google Flow credits: https://support.google.com/flow/answer/16526234
- Gemini API billing (separate future option): https://ai.google.dev/gemini-api/docs/billing/
- n8n Wait: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.wait/

Flow features and account credits vary; no numeric quota or model-specific capability is required by this manual export/import contract.
