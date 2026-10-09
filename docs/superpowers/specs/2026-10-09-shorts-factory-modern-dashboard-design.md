# Shorts Factory — modern dashboard design

Date: 2026-10-09 (Asia/Bangkok)
Status: **Approved on 2026-10-09: user selected 01 Creator Studio ("จัด 01 ได้เลย").**

## Request and recommended direction

The user wants the existing dashboard to feel modern and easier to use, and
asks for suggestions about useful features. They approved an interactive browser
mockup before production code changes. Recommended direction: **Creator Studio**,
with charcoal surfaces, a restrained amber accent, readable Thai typography,
clear status labels, and a mobile layout designed for touch.

The browser mockup contains synthetic data, not production records. Its source is
`.superpowers/brainstorm/93903-1791514771/content/creator-studio-v1.html`
(ignored by Git). The session's `state/server-info` contains its local preview
URL; restart the companion for the same project if the server is stopped.

### Alternatives shown in the preview

| Direction | Benefit | Tradeoff |
| --- | --- | --- |
| Creator Studio — recommended | Charcoal/amber, strong hierarchy, comfortable for checking clips regularly | Requires careful contrast for secondary text |
| Clean Light | Ivory surfaces, restrained amber, easy to read in bright surroundings | Less of a video studio feel |
| Data Ops | Blue accent, compact rows and statistics, efficient for frequent inspection | Less visual emphasis on the individual clip |

All directions keep the same underlying pages. Light/dark remain available in
the final application regardless of the selected visual direction.

## Findings from the current code

- `base.html` supplies a small horizontal pill navigation; headings, spacing,
  and tables have little visual hierarchy. Mobile navigation competes with the
  brand and theme control for horizontal space.
- Settings inputs, the save button, and `.ok` messages have no dedicated styling.
  `settings_save()` redraws stored values after invalid input, losing the user's
  rejected edit even though its comment promises otherwise.
- `_summary()` aggregates both locales and counts all uploaded clips, while
  `analytics.gate_note()` defaults to Thai. Its `published / 30` card can therefore
  appear to reach the channel Gate using uploads from two different audiences.
- Current percentage labels say "ดูจนจบ", while the stored metric is
  `averageViewPercentage`: average fraction of a video watched, not the proportion
  of viewers who completed it. Rename the display without changing measurement.
- Clip details show all drafts and a valid per-clip snapshot chart, but scripts,
  narration, render information, and links need clearer grouping. Rendered Card
  numbers currently start at zero; user-facing Cards should start at one.
- `/now` reads a state file without a heartbeat. It must describe recorded state,
  not claim that the bot is online or show invented render progress.
- Output videos are not mounted in the dashboard. A local MP4 player or true
  thumbnail extraction requires a separate media-serving change.

## First implementation scope

### Shared shell

- Retain existing routes `/`, `/clip/{id}`, `/experiment`, `/now`, `/settings`.
- Desktop: fixed-width sidebar, page breadcrumb, theme control, clear page title,
  explanatory subtitle, and consistent main-content width.
- Mobile: compact header and four-item bottom navigation, safe-area padding,
  two-column metrics, stacked information sections, and clip cards.
- Use local system fonts with Thai fallbacks, shared CSS tokens, inline SVG icons,
  and small vanilla JavaScript. No new frontend dependency or remote font service.
- Preserve stored `theme`, system-theme default, and early theme initialization.
  Theme storage failures must not prevent page rendering or navigation.

### Clip library (`/`)

- Provide an explicit Thai/English channel selector, with Thai selected initially.
  Remember the selected channel within this browser session.
- Four metrics scoped to the selected channel: recorded clips, uploaded clips
  from channel history, day-7 views, and median day-7 average viewing percentage.
  Search/status filters affect the library, not channel-level metrics; label that
  scope and display the visible-row count separately.
- Keep `manifest.day7()` as the authoritative measurement. Missing numbers render
  as unavailable/pending, never zero. Do not replace them with latest snapshots.
- Show channel Gate progress and its warning together. Reaching 30 uploads alone
  does not announce a winning variant; preserve all existing experiment rules.
- Show stored automatic schedule and enabled/disabled state for the selected
  channel. Label the timezone Asia/Bangkok. These are scheduled hours, not a
  promise of when a busy bot will start.
- Search topic/title/clip id; combine channel, search, and status filtering in the
  browser. Provide empty states and a clear/reset action. Keep links usable when
  JavaScript is unavailable; server-render all records.
- Translate known outcomes into human labels with colored badges and text.
  Uploaded clips take precedence over their render outcome. Do not label every
  historical `drafting` record as currently waiting for review: use the matching
  `state.clip_id` and recorded mode for that claim, or show the recorded outcome.
- Preserve unknown outcomes and expose them through fallback labels/filters.
  Do not turn generic failures into a "retry" command in this read-only UI.
- Each row links to clip detail. Decorative covers may use titles/colors as a
  script representation and must not imply that a video thumbnail was extracted.

### Clip detail (`/clip/{id}`)

- Add a back link, locale/status/date metadata, and a prominent existing YouTube
  link when a video id exists. Keep unpublished/draft/404 records usable.
- Latest draft is the primary script card. Preserve access to every prior draft,
  including discarded revisions, in native disclosures.
- Distinguish narration from spoken text; label Cards starting at 1. Show render
  duration and available Card start times without assuming all clips are rendered.
- Provide script copy with a failure message if clipboard access is unavailable.
- Surface the existing pronunciation checklist as text using the stdlib-only
  `app.pronunciation` helpers. State that it checks text, not synthesized audio,
  and that `/say` overrides can change spoken output. Do not import `app.render`.
- Preserve per-clip SVG chart and snapshot table; improve axis labels and dates.
  Render a chart only when the existing helper has enough points. Do not fabricate
  a cumulative library trend by adding snapshots from different clip ages.
- Preserve storyboard and source/research details when present, in clear sections.

### Experiments (`/experiment`)

- Clearly separate locale sections, with readable arm comparison cards, clip/view
  counts, discard/failure counts, official medians, and progress to sample limits.
- Reuse `experiment.verdict()` and existing Gate logic. Never announce a winner
  by color, trophy, sorting, or copy before the existing verdict allows it.
- Keep prompt clauses inspectable. Label category statistics as observational.

### Recorded state (`/now`)

- Present stored mode in plain Thai, topic and clip links when available,
  parked/auto-pick/review waits, pronunciation overrides, and recent uploads.
- State "สถานะที่บันทึกไว้" and "อ่านไฟล์เมื่อเปิดหน้า". If showing file mtime,
  explicitly call it file modification time, not bot heartbeat or last activity.
- Preserve unknown state fields in a raw-data disclosure. Continue avoiding huge
  script/suggestion dumps in the main page.

### Settings (`/settings`)

- Use per-channel cards, labeled enable checkboxes, accessible fields, timezone,
  schedule examples, and wait-time explanations.
- Group primary/fallback model controls together, retain the bot-provided catalog,
  and label the catalog's recorded fetch time without promising a model is tested.
- Keep existing field names and the single `POST /settings`. Validate schedule and
  models before either is written. Preserve rejected field values when showing
  errors; give feedback with status/alert semantics.
- Add a clear save button and success state. Explain the user-facing effect:
  changes take effect on the bot's next tick/call, while YouTube upload approval
  still happens in Telegram. Move file-path/implementation explanations out of
  the default product flow.

## Architecture and boundaries

FastAPI/Jinja remain the rendering path. Dashboard view helpers prepare labels,
channel summaries, and presentation data from existing manifest/history/state/
schedule/catalog modules. Templates own semantic layout, CSS owns themes and
responsive rules, and JavaScript owns progressive client-side controls.

Preserve `/data:ro`, credential-free dashboard environment, basic auth on every
nginx path, and the sole settings write into `/config`. Do not change the bot,
its Telegram review/upload flow, analytics algorithms, experiment assignment,
credentials, compose volumes, or media-serving routes for this redesign.
Pillow and edge-tts must remain absent from the dashboard process.

## Feature recommendations

| Priority | Suggestion | Scope |
| --- | --- | --- |
| Now | Search/status/channel filters, correct channel KPIs, readable schedules | Included in redesign |
| Now | Latest-script focus, copy action, pronunciation checklist | Included in redesign using existing recorded data |
| Now | Preserve invalid settings edits and give explicit save/error feedback | Included in redesign |
| Next | Local video preview and real thumbnails | Separate proposal: read-only `/output` mount, bounded file serving, missing-file handling |
| Next | Real heartbeat and explicit job-stage timestamps | Separate bot change; useful for telling stale state from a long render |
| Later | Posting-time comparison and distribution analysis | Wait for sufficient per-channel samples; observational labels until justified |
| Later | Topic recommender from historical performance | Preserve learning Gate; do not infer winners from insufficient data |

## Verification and acceptance

- Baseline on 2026-10-09: `tests/test_dashboard.py` **22 passed** after supplying
  the already-pinned `python-multipart==0.0.20` in an isolated temporary dependency
  directory. The system Python lacked it; no application code change was needed.
- Verify all five views, empty data, missing/broken manifests, legacy records,
  unknown outcomes/state keys, and clip 404 responses.
- Add focused regressions for locale-isolated metrics/Gate, missing values,
  correct percentage labels, prior drafts, invalid settings input preservation,
  and unchanged write-route/import boundaries.
- Browser checks: desktop 1440px, tablet around 768px, phone 390px and 320px;
  both themes, search + status + channel combinations, no-results state, copy
  fallback, settings validation, keyboard navigation, and unknown labels.
- Check no page-wide horizontal overflow and no controls obscured by mobile nav.
  Normal text contrast target 4.5:1, visible focus, and touch controls around 44px;
  reduced-motion preference disables nonessential animation.
- No production deployment or Git commit is performed at this design stage.
  Implementation, commit, and deployment status must remain explicit in stack
  memory. Existing unrelated `hermes-agent/docker-compose.yml` edit is outside scope.

## References

- Repository: `docs/adr/0004`, `0007`, `0008`, `0009` and stack index memory.
- [YouTube Analytics metric definitions](https://developers.google.com/youtube/analytics/metrics#Watch_Time_Metrics)
  define average viewing percentage; the UI should not describe completion rate.
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/) provides contrast, reflow, keyboard
  focus, and target-size criteria used for the visual acceptance checks.

## Review status

Reviewed for scope, data semantics, security boundaries, missing data, and false
live-state claims. User approved Creator Studio and the written scope on
2026-10-09. Implementation uses isolated worktree `shorts-creator-studio` on
`codex/shorts-factory-creator-studio`; existing Hermes edits remain in the primary
checkout. Production deployment is a separate release step.

Implementation and acceptance checks completed on 2026-10-09. Final focused review
at `66d2abd` passed with no outstanding findings. Main merge/push `565de60` and
scoped NAS deployment completed after the user's release authorization. Managed
worktree archived/removed and previews preserved. Exact checks, unchanged auth
credentials, proxy smoke limitation and release status are recorded in
`shorts-factory/.notes/00_INDEX.md` and `daily_log.md`.
