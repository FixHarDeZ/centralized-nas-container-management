# Shorts Factory Creator Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execute inline in the approved session; isolate from concurrent Hermes work.

**Goal:** Deliver the approved Creator Studio redesign across all five dashboard views with correct per-channel statistics, useful clip controls, and accessible settings.

**Architecture:** Keep FastAPI/Jinja and existing file readers. Put reusable presentation labels/date/number formatting in `app/dashboard_view.py`; `dashboard.py` prepares page contexts. Shared Jinja partials, CSS tokens, and vanilla JavaScript own layout and progressive browser controls.

**Tech Stack:** Python, FastAPI, Jinja2, HTML/CSS, inline SVG, vanilla JavaScript, pytest.

## Global Constraints

- Preserve `/data:ro`, credential-free dashboard environment, nginx basic auth, and sole writing route `POST /settings` into `/config`.
- No PIL/edge_tts import, frontend dependency, remote font service, bot change, or analytics/experiment algorithm change.
- Preserve `manifest.day7()` as authoritative; missing statistics stay unavailable rather than zero.
- Gate and uploaded counts are per channel; state is recorded data, not heartbeat.
- Use existing settings field names and validate both payloads before writing either file.
- Both themes and responsive desktop/mobile layouts; target normal text contrast 4.5:1, visible focus, roughly 44px touch controls, reduced motion.
- Worktree: `/Users/peerawat.ujaiyen/.codex/worktrees/shorts-creator-studio/centralized-nas-container-management`; branch `codex/shorts-factory-creator-studio`.
- Verification command: `PYTHONPATH=/tmp/shorts-factory-dashboard-review-deps:shorts-factory python3 -m pytest shorts-factory/tests/test_dashboard.py -q --tb=short`.

---

### Task 1: Correct data and presentation contracts

**Files:** `shorts-factory/app/dashboard.py`, new `shorts-factory/app/dashboard_view.py`, `shorts-factory/tests/test_dashboard.py`.

**Interfaces:** `_row(record, state=None) -> dict` keeps existing keys and adds `locale_code`, `title`, `status`, `search`. `_summary(rows, locale="th") -> dict` isolates rows and history by locale and exposes `measured` count. `dashboard_view.status(record, state=None) -> dict` returns closed tone/key with human label and raw outcome fallback; `format_date(value) -> str`, `format_number(value) -> str` are registered Jinja filters.

- [ ] Add regression tests before code, including:

```python
def test_summary_does_not_mix_channels(client, data_dir):
    from app import dashboard, history
    history.PATH.write_text(json.dumps([
        {"video_id": "th1"}, {"video_id": "en1", "locale": "en"}
    ]))
    rows = [dashboard._row({"locale": "th", "snapshots": [{"age_days": 7, "views": 10, "percent": 40}]}),
            dashboard._row({"locale": "en", "snapshots": [{"age_days": 7, "views": 900, "percent": 90}]})]
    assert dashboard._summary(rows, "th")["views"] == 10
    assert dashboard._summary(rows, "en")["published"] == 1
```

- [ ] Run focused new tests; confirm failure due to missing locale-aware behavior.
- [ ] Implement scoped statistics and presentation helpers. Normalize locale through `locales.get(record.get("locale"))["code"]`; use `history.video_ids(locale)`; collect percents only when not None. Published status takes precedence. A matching reviewed record may show recorded review mode; other drafts retain their historical status.

```python
mine = [row for row in rows if row["locale_code"] == locale]
percents = [row["percent"] for row in mine if row["percent"] is not None]
summary = {"published": len(history.video_ids(locale)), "views": sum(row["views"] or 0 for row in mine),
           "median": median(percents) if percents else None, "total": len(mine),
           "gate_clips": analytics.GATE_CLIPS, "measured": sum(row["views"] is not None for row in mine)}
```

- [ ] Verify legacy/unknown locales, 0 versus None metrics, unknown outcomes and history-scoped upload counts with dashboard suite.

### Task 2: Shared shell and clip library

**Files:** `app/templates/base.html`, new `app/templates/_icons.html`, `app/templates/clips.html`, `app/static/style.css`, `app/static/app.js`, `tests/test_dashboard.py` (all under `shorts-factory/`).

**Interfaces:** Base provides `page_header`/`content` blocks, semantic active navigation, icons macro, and common feedback styles. Route context adds `channels` containing code/label/summary/gate/schedule and all rows. Library row attributes `data-locale`, `data-status`, `data-outcome`, `data-search` drive client controls.

- [ ] Add meaningful regressions for channel context/labeling and unavailable values; preserve existing newest-first/filter/day7 tests.
- [ ] Render channels and their metrics from the scoped summaries:

```jinja2
{% for channel in channels %}
<section data-channel-panel="{{ channel.code }}" aria-label="สรุปช่อง{{ channel.label }}">
  <div class="metric-number">{{ channel.summary.views|number }}</div>
  <p>{{ channel.summary.measured }} คลิปมีสถิติ Day 7</p>
</section>
{% endfor %}
```

- [ ] Build the approved sidebar/header/mobile nav, dark/light token palette, metric cards, Gate progress and stored schedule. Decorated title covers are script representations, not extracted thumbnails.

```css
:root { --bg:#f6f5f1; --surface:#fff; --text:#242727; --muted:#636967; --accent:#996000; }
[data-theme="dark"] { --bg:#101211; --surface:#191c1a; --text:#f0f1e9; --muted:#a4aca2; --accent:#edc66e; }
[hidden] { display:none!important; }
:focus-visible { outline:3px solid var(--accent); outline-offset:3px; }
```

- [ ] Implement combined filtering and row-count/no-results feedback. Channel changes also select that channel's summary/Gate/schedule; status/search never change KPI scope. Use guarded sessionStorage/localStorage access; preserve readable server HTML without JavaScript.

```javascript
const matches = row.dataset.locale === selectedChannel &&
  (!selectedStatus || row.dataset.status === selectedStatus) &&
  (row.dataset.search || '').toLocaleLowerCase().includes(query);
row.hidden = !matches;
```

- [ ] Verify HTML suite and actual browser search/channel/status/reset/no-results controls in both themes.

### Task 3: Clip workspace and experiments

**Files:** `app/dashboard.py`, `app/templates/clip.html`, `app/templates/experiment.html`, `app/static/app.js`, `tests/test_dashboard.py`.

**Interfaces:** Clip context adds `latest`, `previous_drafts`, `checks=pronunciation.collect(latest_script, locale)`, readable status/locale, and source metadata. Keep `drafts`, `cards`, `snapshots`, `day7`, and `_chart()` for compatibility. Experiment sections keep existing arms/verdict/gate/category/clauses data.

- [ ] Add tests proving pronunciation checklist is visible and all drafts remain reachable, while one-point chart stays absent and gate does not become an inferred winner.
- [ ] Add latest-script/previous-draft sections with 1-based Cards and accessible disclosures:

```jinja2
{% for card in latest.script.cards or [] %}
<article class="script-scene"><p>Card {{ loop.index }}</p><p>{{ card.narration }}</p>
{% if card.spoken %}<p class="spoken">คำอ่าน: {{ card.spoken }}</p>{% endif %}</article>
{% endfor %}
```

- [ ] Render checklist terms/readings/cards/context safely through Jinja escaping. State text-only checking and `/say` override limits. Keep sources/storyboard/snapshots available and existing YouTube link prominent. Clipboard copy catches permission/unavailable failures and displays feedback.
- [ ] Style experiment arms/progress and category summaries separately by locale; preserve verdict and warnings, avoid winner styling before gate allows it. Native details expose exact prompt clauses.
- [ ] Run dashboard tests; browser verify detail/404/experiments, disclosure and copy feedback.

### Task 4: Recorded state and settings validation

**Files:** `app/dashboard.py`, `app/templates/now.html`, `app/templates/settings.html`, `tests/test_dashboard.py`.

**Interfaces:** State context preserves `summary`, unknown keys, `say`, `uploads`; adds readable mode and waiting-job presentation. `_settings_page(..., submitted=None)` accepts original submitted fields for rejected forms; original stored data remains used on successful GET/save.

- [ ] Write failing tests for rejected hour/minute/model preservation and prove invalid input changes neither settings file.

```python
def test_rejected_schedule_keeps_the_edit(client, config_dir):
    reply = client.post('/settings', data={
        'th_enabled': 'on', 'th_hours': '8,99', 'th_minutes': '17',
        'en_hours': '20', 'en_minutes': '30', 'model_primary': 'mimo-v2.5'})
    assert reply.status_code == 400
    assert 'value="8,99"' in reply.text
    assert 'value="17"' in reply.text
    assert not (config_dir / 'schedule.json').exists()
```

- [ ] Pass original form text back on ValueError; keep the parsed payload only for validation/save. Include an unknown submitted model as an escaped selected invalid option so the edit remains inspectable.

```python
except ValueError as exc:
    return _settings_page(request, schedule.settings(), model_choice.stored(),
                          error=str(exc), status=400, submitted=form)
```

- [ ] Build channel/model cards, labels, timezone/examples, clear submit button, role=status/alert feedback. State view uses recorded-state wording and exposes unknown keys without declaring live health.
- [ ] Run settings/dashboard regressions and browser verify success/error feedback against isolated demo config.

### Task 5: Browser verification, review and delivery

**Files:** `shorts-factory/README.md`, stack `.notes/00_INDEX.md`/`daily_log.md`, this plan and approved spec.

**Interfaces:** Local preview runs real `app.dashboard` against temporary synthetic data/config, never NAS data or credentials. Screenshots use approved CUA browser tooling.

- [ ] Run full dashboard + pronunciation suites and shared-sync checks; run `node --check app/static/app.js`, targeted Ruff and `git diff --check`.
- [ ] Start `PYTHONPATH=shorts-factory DATA_DIR=<temporary-demo-data> CONFIG_DIR=<temporary-demo-config> python3 -m uvicorn app.dashboard:app --host 127.0.0.1 --port 8071` using an available isolated dependency runtime.
- [ ] Browser verify five real views, empty/404/error forms, theme storage resilience and keyboard focus. Check desktop1440, tablet768 and phone390/320; read DOM widths and verify fixed navigation does not hide controls.
- [ ] Save desktop/mobile screenshots, open actual implementation preview for user, and review diff for escaping, metric semantics, write/import boundaries and unrelated-file changes.
- [ ] Update README, approved spec/plan checkboxes and both stack notes with exact checks, remaining release steps, and actual commit/deploy status. Verify documents and status before final delivery.

## Plan self-review

Coverage maps shared shell/library to Task 2, clip/experiment to Task 3,
state/settings to Task 4, per-channel semantics/boundaries to Task 1, and
verification/memory to Task 5. No bot/media/heartbeat/recommender change is included.
Tests precede behavioral changes. Visual CSS/layout verification uses the real
browser; no implementation-mirroring CSS tests are needed.
