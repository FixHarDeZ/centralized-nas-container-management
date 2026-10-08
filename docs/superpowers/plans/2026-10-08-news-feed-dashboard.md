# Modern news-feed Dashboard Implementation Plan

> Execute in this session, using the approved design at `docs/superpowers/specs/2026-10-08-news-feed-dashboard-design.md`. Review the final diff with requesting-code-review before delivery.

**Goal:** A modern editorial dashboard with readable Thai news, useful summary data, robust filters and responsive navigation across all six sections.

**Architecture:** Keep FastAPI and all existing APIs. Separate the visual system into `dashboard.css` and pure date/filter/safety helpers into `dashboard-utils.js`; `app.js` owns API requests and UI state.

**Tech Stack:** Existing vanilla HTML/CSS/JavaScript, Chart.js, FastAPI, pytest; Node's built-in test runner for behavior helpers, no added packages.

## Global Constraints

- All six sections and existing copy/star/expiry/chart/config features remain available.
- Default page is News Timeline on all screen sizes. No new framework or dependencies.
- Stats must distinguish aggregate 24h data from the latest 100 loaded articles; errors never become fake zero counts.
- Compute the next digest in Asia/Bangkok independent of browser timezone.
- Escape title/summary/source and allow only http/https article links.
- Do not send notifications, fetch production feeds, read secrets, deploy, or commit during preview verification.
- Memory updates belong to `news-feed/.notes/` only. No Codex/Anthropic co-author trailers.

## Task 1: Dashboard shell and visual system

Files: `news-feed/app/static/index.html`, new `news-feed/app/static/dashboard.css`.

- [x] Replace inline stylesheet with a stylesheet link; add system font, off-white canvas, dark slate sidebar and teal accent tokens.
- [x] Keep existing section/input/action IDs; add `data-tab` to desktop/mobile navigation. Add `page-title`, `page-description`, `page-eyebrow` and a refresh action that calls `refreshCurrentTab()`.
- [x] Add news overview IDs `stat-articles`, `stat-sources`, `stat-next-digest`, `stat-watchlist`, `overview-status`, `overview-retry`, `activity-fetch`, `activity-digest`, `activity-next`, `activity-watchlist`.
- [x] Add status filters via `setNewsStatus('all'|'summarized'|'sent')`, `news-results`, `news-list`, `news-source-filter`, `news-search`; preserve fetch/sort controls.
- [x] Use accessible inline SVG navigation icons and responsive sidebar/mobile drawer. Group Settings and put save/danger actions below config groups.
- [x] Verify markup parses, every original hook remains present, one active default section, and no duplicated IDs; visual verification is in Task 3 rather than tests that assert styling.

## Task 2: Reliable data, news interactions, safety and next digest

Files: `news-feed/app/static/app.js`, new `news-feed/app/static/dashboard-utils.js`, new `news-feed/tests/dashboard.test.cjs`.

- [x] Write and run failing Node tests for Bangkok midnight rollover/empty schedule, text/URL safety, combined news filters and invalid persisted watchlist data.
- [x] Implement pure helpers `nextDigest(times, now)`, `escapeText(value)`, `safeArticleUrl(value)`, `filterArticles(articles, {query, source, status}, sentIds)`, `readWatchlist(value)`; export to both browser and CommonJS for the test runner.
- [x] Make navigation use `data-tab` rather than button order. Update active state/page headings and use per-tab loading/error/retry feedback; protect settings loading and disable saving until populated.
- [x] Load health/source counts/schedule/history independently for overview. Provide partial failure status and retry; show zero only on successful empty data.
- [x] Keep news filter/sort state across refresh, show summary preview, expand with native details/summary, escape all external article content and reject unsafe links.
- [x] Keep price filters on refresh, style/chart colors consistently, and show benchmark data as static reference rather than fresh rankings.
- [x] Refresh summary after existing fetch, watchlist and schedule actions; keep existing API contracts.
- [x] Run `node --test news-feed/tests/dashboard.test.cjs`, `node --check` for both scripts and existing `pytest tests/` in news-feed.

## Task 3: Integration, review and delivery

Files: `news-feed/README.md`, `news-feed/.notes/daily_log.md`, `news-feed/.notes/00_INDEX.md`, design and this plan.

- [x] Serve local dashboard with a disposable mock API server in `/private/tmp`; support realistic article/source/schedule/history/model data and failure fixtures. Writes go only to in-memory fixtures.
- [ ] Use browser UI to inspect desktop/tablet/mobile layouts, all tabs, filter preservation, details, copy/star/history, config loading and error/retry. Do not click real production notification actions.
- [x] Review the final diff for scope, safety, responsiveness and regressions; fix actionable findings and rerun covering checks.
- [x] Update README, stack memory and plan with actual evidence and remaining limitations; record release status as it happens.
- [ ] Open local preview in Codex, deliver link and summary with useful future enhancement suggestions.

## Progress

- Design approved; implementation started on `codex/news-feed-modern-dashboard`.
- Task 1 complete: all 67 original hooks retained, 103 unique IDs, labels/default section/CSS structure checked.
- Task 2 complete: 133 pytest + 22 Node tests passed, including America/New_York timezone. Regression-first repairs protect stale async responses, retain absent source selections and defer/coalesce settings refresh during pending saves. Both JavaScript syntax checks and scoped diff checks pass.
- Production StaticFiles verified with TestClient: HTML/CSS/2 JS assets return 200 with correct MIME types; no scheduler lifespan or external services invoked.
- Browser permission denied at `http://127.0.0.1:8874`; asynchronous authorization question pending. No browser workaround attempted. Visual/runtime browser verification is still open.
- Final code review passed with no remaining actionable findings; two additional ordering probes cover failed refresh and duplicate Save protection.
- User subsequently authorized commit, push, merge main and deployment. Release verification is in progress. Release uses an isolated checkout/payload to preserve unrelated work in the shared workspace.
