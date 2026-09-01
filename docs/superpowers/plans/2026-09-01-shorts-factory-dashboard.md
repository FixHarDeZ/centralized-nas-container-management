# shorts-factory read-only dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task by
> task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give shorts-factory a LAN-only web view of the record it already
writes to disk — every Clip Manifest, the experiment arms, the current bot
state — without the bot process gaining an HTTP surface or the dashboard gaining
any way to write.

**Architecture:** A second container built from the **same image** as the bot,
started with a different command (`python -m app.dashboard`), mounting the
bot's data volume read-only. It imports `app.manifest`, `app.experiment`,
`app.analytics` and `app.history` directly, so its numbers can
never disagree with what the bot answers in Telegram. An nginx sidecar publishes
port 5069 with basic auth; the FastAPI app is `expose:`-only.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, Jinja2, nginx:alpine, pytest.

**Spec:** `docs/superpowers/specs/2026-09-01-shorts-factory-dashboard-design.md`
— read it before starting. The plan does not repeat the spec's reasoning.

---

## Global Constraints

These apply to every task. They are environment facts, not preferences.

- **Working directory is `shorts-factory/`** unless a path says otherwise. Paths
  in this plan are relative to the repository root.
- **The dashboard must never write.** No POST/PUT/PATCH/DELETE route, ever. The
  volume mounts are `:ro`. Task 2 adds a test that enforces this; do not weaken
  it.
- **Do not modify `app/main.py`, `app/render.py`, `app/script.py`,
  `app/footage.py`, `app/youtube.py`, `app/trends.py`, `app/snapshots.py`,
  `app/backfill.py` or `app/retention.py`.** This feature adds a reader; the bot
  keeps its exact current behaviour. `app/manifest.py`, `app/experiment.py`,
  `app/analytics.py` and `app/history.py` are read from but not edited either.
- **No `cpus:` in any compose service.** DSM's kernel has no CFS bandwidth
  control and the Docker daemon refuses to create the container:
  `NanoCPUs can not be set, as your kernel does not support CPU CFS scheduler`.
- **`mem_limit` is required on every new service.** The host had a whole-box OOM
  on 2026-08-19.
- **Port 5069.** 5063-5066 and 5068-5070 are taken by other stacks; 5060 and
  5061 are unusable because browsers block them as SIP ports.
- **Never commit** `.env`, `.env.deploy`, `nginx/.htpasswd`, or any real
  hostname, IP or password. Use `<NAS_HOST>` / `<NAS_USER>` placeholders in
  documentation.
- **Thai UI copy.** The bot's messages and the repo's other dashboards are Thai;
  match that. Code, comments and commit messages are English.
- **`DATA_DIR` defaults to `/data`** and is read at import time by
  `app/manifest.py` (`DIR = Path(os.environ.get("DATA_DIR", "/data")) / "clips"`),
  `app/history.py`. Tests must set `DATA_DIR` in the
  environment **before** importing those modules, or use
  `importlib.reload`. Task 2's test shows the pattern; copy it.
- **Do not run `git commit`.** Each task's final step says "commit"; run only
  the `git add` part of it and leave the work staged for human review. Never
  add a `Co-Authored-By` trailer of any kind if a commit is ever made.
- **Task 0 and Task 9 are not yours.** They touch the sops vault and the live
  NAS and are performed by the human operator. Task 0 is already done before
  you start; stop after Task 8 and report.

### Data shapes you will read

A Manifest (`/data/clips/<id>.json`, written by `app/manifest.py`):

```json
{
  "id": "20260831-142233-004",
  "created_at": "2026-08-31T14:22:33",
  "topic": "ทำไม container ถึงกิน RAM เยอะ",
  "variant": "shock_number",
  "explore": false,
  "scripts": [{"at": "2026-08-31T14:24:01", "script": {"hook": "...", "cards": [], "title": "...", "description": "...", "hashtags": [], "category": "devops"}}],
  "outcome": "rendered",
  "published": true,
  "video_id": "abc123",
  "snapshots": [{"date": "2026-09-07", "age_days": 7, "views": 182, "percent": 41.2}],
  "render": {"duration": 47.3, "cards": [{"start": 0.0}, {"start": 8.2}]},
  "storyboard": {}
}
```

Not every key is present on every Manifest — `backfill.py` reconstructs old ones
with only some fields, and a Manifest opened seconds ago has `outcome:
"drafting"` and an empty `scripts` list. **Every read must use `.get()` with a
default.** A missing key is normal, not an error.

`/data/state.json` keys: `mode`, `topic`, `clip_id`, `script`, `style`,
`message_id`, `upload_message_id`, `trends_message_id`, `suggested`,
`suggested_at`, `parked`, `auto_pick`, `offset`, `last_snapshot`,
`last_auto_trends`.

`/data/say.json` is a flat `{"wrong": "right"}` map.

### Functions you will call (do not re-implement these)

| Call | Returns |
| :--- | :--- |
| `manifest.load_all()` | `list[dict]` — every Manifest, sorted by filename (= chronological) |
| `manifest.load(clip_id)` | `dict \| None` |
| `manifest.day7(record)` | the first snapshot with `age_days >= 7`, or `None` |
| `experiment.tally(records)` | `{variant_name: {"clips": int, "discarded": int, "failed": int, "views": int, "percents": list[float]}}`, plus an `"explore"` key |
| `experiment.verdict(counts)` | Thai verdict string |
| `experiment.by_category(records)` | `{category: {"clips", "views", "percents", "trend"}}` |
| `experiment.VARIANTS` | `{name: prompt_clause}` |
| `analytics.gate_note()` | Thai warning string, or `None` once past the Gate |
| `history.load()` | `list[dict]` with `video_id`, `title`, `topic`, `uploaded_at` |
| `dashboard._say()` | the `/data/say.json` map, `{}` if unreadable. Defined in Task 6 — **do not** import `app.render` for this: it drags Pillow and edge-tts into the only LAN-facing process, and the workstation cannot install them. |

---

## File Structure

Create:

| File | Responsibility |
| :--- | :--- |
| `shorts-factory/app/dashboard.py` | FastAPI app: routes only. Each route loads via the modules above, shapes a dict, renders a template. No business logic. |
| `shorts-factory/app/templates/base.html` | Layout, nav, stylesheet link |
| `shorts-factory/app/templates/clips.html` | `/` |
| `shorts-factory/app/templates/clip.html` | `/clip/{id}` |
| `shorts-factory/app/templates/experiment.html` | `/experiment` |
| `shorts-factory/app/templates/now.html` | `/now` |
| `shorts-factory/app/static/style.css` | One stylesheet, dark, mobile-readable |
| `shorts-factory/nginx/nginx.conf` | Basic auth on every path, proxy to the app |
| `shorts-factory/tests/test_dashboard.py` | All dashboard tests |
| `docs/adr/0007-dashboard-is-a-separate-read-only-container.md` | Why the HTTP surface came back |

Modify: `shorts-factory/requirements.txt`, `shorts-factory/docker-compose.yml`,
`shorts-factory/README.md`, `shorts-factory/.notes/00_INDEX.md`,
`shorts-factory/.notes/daily_log.md`, `docs/adr/0002-shorts-factory-has-no-http-surface.md`,
root `CLAUDE.md`, root `README.md`.

Generated, never committed: `shorts-factory/nginx/.htpasswd`.

---

## Task 0: Vault credentials and `.env`

Do this first. Task 7 runs `docker compose config`, which reads `env_file: .env`
— and `.env` is gitignored, so on a fresh checkout it does not exist yet and the
verification step that catches the YAML-duplicate-key trap cannot run.

**Files:** none committed. Creates `shorts-factory/.env` (gitignored) and
`shorts-factory/nginx/.htpasswd` (gitignored).

- [ ] **Step 1: Add the dashboard credentials to the vault**

Use the `adding-vault-secret` skill. The keys are
`stacks.shorts_factory.dashboard.basic_auth_user` and
`stacks.shorts_factory.dashboard.basic_auth_password`. Vault edits go through
`make edit-vault`; never edit `secrets/vault.sops.yaml` directly.

- [ ] **Step 2: Render the env files**

```bash
cd /Users/peerawat.ujaiyen/MyCode/centralized-nas-container-management && make secrets
test -f shorts-factory/.env && echo "env ok"
```

- [ ] **Step 3: Generate the .htpasswd**

```bash
mkdir -p shorts-factory/nginx
htpasswd -cB shorts-factory/nginx/.htpasswd <username>   # enter the vault password
git check-ignore -v shorts-factory/nginx/.htpasswd       # must print a .gitignore line
```

If `git check-ignore` prints nothing, add `shorts-factory/nginx/.htpasswd` to
`.gitignore` before going any further.

- [ ] **Step 4: Nothing to commit**

Confirm with `git status --short` that neither `.env` nor `.htpasswd` shows up.

---

## Task 1: Dependencies

**Files:**
- Modify: `shorts-factory/requirements.txt`

**Interfaces:**
- Produces: `fastapi`, `uvicorn`, `jinja2`, `httpx`'s `TestClient` available to
  every later task.

- [ ] **Step 1: Add the pins**

Append to `shorts-factory/requirements.txt`, below the existing `edge-tts` pin
and above the `pytest` line:

```
# The dashboard only (app/dashboard.py). app.main never imports these; they are
# in the shared image because the dashboard runs from it. See docs/adr/0007.
fastapi==0.115.6
uvicorn==0.34.0
jinja2==3.1.5
```

- [ ] **Step 2: Verify the install resolves**

Run from `shorts-factory/`:

```bash
python -m venv /tmp/sf-venv && /tmp/sf-venv/bin/pip install -q -r requirements.txt && /tmp/sf-venv/bin/python -c "import fastapi, uvicorn, jinja2; print('ok')"
```

Expected: `ok`. If `pillow==12.3.0` or `edge-tts` fails to build locally, skip
this step — it is verified in the container in Task 9 — and say so in the task
report rather than changing any existing pin.

- [ ] **Step 3: Commit**

```bash
git add shorts-factory/requirements.txt
git commit -m "chore(shorts-factory): add fastapi/uvicorn/jinja2 for the dashboard"
```

---

## Task 2: App skeleton, `/healthz`, and the read-only guard

**Files:**
- Create: `shorts-factory/app/dashboard.py`
- Create: `shorts-factory/tests/test_dashboard.py`

**Interfaces:**
- Produces: `app.dashboard.app` (a `FastAPI` instance), `app.dashboard.TEMPLATES`
  (a `jinja2.Environment`-backed `Jinja2Templates`), and the
  `client`/`data_dir` pytest fixtures every later task's tests reuse.

- [ ] **Step 1: Write the failing tests**

Create `shorts-factory/tests/test_dashboard.py`:

```python
"""The dashboard reads and only reads.

`DATA_DIR` is read at import time by app.manifest/app.history/app.render, so the
environment is set before the import happens — hence the fixture ordering and
the reloads below.
"""
import importlib
import json
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """A /data that looks like a live one: two Manifests, state, say."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    clips = tmp_path / "clips"
    clips.mkdir()

    (clips / "20260801-120000-000.json").write_text(json.dumps({
        "id": "20260801-120000-000",
        "created_at": "2026-08-01T12:00:00",
        "topic": "ทำไม container กิน RAM",
        "variant": "shock_number",
        "explore": False,
        "outcome": "rendered",
        "published": True,
        "video_id": "vid1",
        "scripts": [{"at": "2026-08-01T12:02:00", "script": {
            "title": "RAM หายไปไหน", "category": "devops",
            "cards": [{"narration": "การ์ดหนึ่ง", "spoken": "การ์ดหนึ่ง"}],
        }}],
        "snapshots": [{"date": "2026-08-08", "age_days": 7, "views": 182, "percent": 41.2}],
        "render": {"duration": 47.3, "cards": [{"start": 0.0}]},
    }, ensure_ascii=False), encoding="utf-8")

    (clips / "20260802-120000-000.json").write_text(json.dumps({
        "id": "20260802-120000-000",
        "created_at": "2026-08-02T12:00:00",
        "topic": "หัวข้อที่ถูกทิ้ง",
        "variant": "question",
        "outcome": "discarded",
        "scripts": [],
    }, ensure_ascii=False), encoding="utf-8")

    (tmp_path / "state.json").write_text(json.dumps(
        {"mode": "idle", "offset": 42, "last_snapshot": "2026-08-08"}), encoding="utf-8")
    (tmp_path / "say.json").write_text(json.dumps(
        {"ทีเอไอ": "ไทย"}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "history.json").write_text(json.dumps([
        {"video_id": "vid1", "title": "RAM หายไปไหน", "topic": "ทำไม container กิน RAM",
         "uploaded_at": "2026-08-01T13:00:00"}]), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def client(data_dir):
    """A client whose modules were imported *after* DATA_DIR was set."""
    from app import history, manifest, render
    for module in (manifest, history, render):
        importlib.reload(module)
    from app import dashboard
    importlib.reload(dashboard)
    return TestClient(dashboard.app)


def test_healthz(client):
    reply = client.get("/healthz")
    assert reply.status_code == 200
    assert reply.json() == {"ok": True}


def test_no_route_can_write(client):
    """Read-only is a property of the code, not only of the :ro mount."""
    from app import dashboard
    for route in dashboard.app.routes:
        allowed = getattr(route, "methods", set()) or set()
        assert allowed <= {"GET", "HEAD"}, f"{route.path} allows {allowed}"
```

- [ ] **Step 2: Run them and watch them fail**

```bash
cd shorts-factory && python -m pytest tests/test_dashboard.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'app.dashboard'`.

- [ ] **Step 3: Write the minimal app**

Create `shorts-factory/app/dashboard.py`:

```python
"""A window onto what the bot has already written down.

Runs as its own container from the same image as the bot, with /data mounted
read-only, and imports the bot's own modules so its figures cannot drift from
the ones Telegram reports. It defines no route that writes: see docs/adr/0007.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HERE = Path(__file__).parent

app = FastAPI(title="shorts-factory", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
TEMPLATES = Jinja2Templates(directory=HERE / "templates")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
```

Create the directories the mount and the template loader need, so the import
does not fail on an empty checkout:

```bash
mkdir -p shorts-factory/app/static shorts-factory/app/templates
touch shorts-factory/app/static/style.css
```

- [ ] **Step 4: Run the tests**

```bash
cd shorts-factory && python -m pytest tests/test_dashboard.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add shorts-factory/app/dashboard.py shorts-factory/tests/test_dashboard.py shorts-factory/app/static/style.css
git commit -m "feat(shorts-factory): dashboard app skeleton with a read-only route guard"
```

---

## Task 3: Layout and stylesheet

**Files:**
- Create: `shorts-factory/app/templates/base.html`
- Modify: `shorts-factory/app/static/style.css`

**Interfaces:**
- Produces: a `base.html` that every page template extends with
  `{% block content %}`, and the CSS classes `.grid`, `.card`, `.muted`,
  `.warn`, `.pill`.

- [ ] **Step 1: Write the layout**

Create `shorts-factory/app/templates/base.html`:

```html
<!doctype html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}shorts-factory{% endblock %}</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <nav>
    <a href="/">คลิป</a>
    <a href="/experiment">การทดลอง</a>
    <a href="/now">สถานะตอนนี้</a>
  </nav>
  {% if gate %}<p class="warn">{{ gate }}</p>{% endif %}
  <main>{% block content %}{% endblock %}</main>
</body>
</html>
```

- [ ] **Step 2: Write the stylesheet**

Replace `shorts-factory/app/static/style.css`:

```css
:root { color-scheme: dark; --bg:#14161a; --fg:#e8eaee; --muted:#9aa2ad; --line:#272b32; --accent:#ffd24a; }
* { box-sizing: border-box; }
body { margin:0; padding:1rem; background:var(--bg); color:var(--fg);
       font:16px/1.5 system-ui, -apple-system, "Noto Sans Thai", sans-serif; }
nav { display:flex; gap:1rem; padding-bottom:.75rem; border-bottom:1px solid var(--line); margin-bottom:1rem; }
nav a { color:var(--accent); text-decoration:none; }
a { color:var(--accent); }
table { width:100%; border-collapse:collapse; }
th, td { text-align:left; padding:.5rem .4rem; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:600; font-size:.85rem; }
.muted { color:var(--muted); }
.warn { background:#3a2f14; border:1px solid #6b551f; padding:.6rem .8rem; border-radius:6px; }
.pill { display:inline-block; padding:.05rem .5rem; border:1px solid var(--line); border-radius:999px; font-size:.8rem; }
.card { border:1px solid var(--line); border-radius:8px; padding:.8rem; margin-bottom:.8rem; }
.grid { display:grid; gap:.8rem; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); }
pre { white-space:pre-wrap; word-break:break-word; margin:0; }
@media (max-width:600px) { body { padding:.6rem; } th, td { padding:.4rem .25rem; font-size:.9rem; } }
```

- [ ] **Step 3: Commit**

```bash
git add shorts-factory/app/templates/base.html shorts-factory/app/static/style.css
git commit -m "feat(shorts-factory): dashboard layout and stylesheet"
```

---

## Task 4: `/` — the Clip list

**Files:**
- Modify: `shorts-factory/app/dashboard.py`
- Create: `shorts-factory/app/templates/clips.html`
- Modify: `shorts-factory/tests/test_dashboard.py`

**Interfaces:**
- Consumes: `TEMPLATES`, `app` from Task 2; `base.html` from Task 3.
- Produces: `dashboard._row(record) -> dict` with keys `id`, `created_at`,
  `topic`, `variant`, `explore`, `outcome`, `published`, `views`, `percent`.
  Task 5 reuses `_row` for nothing, but Task 6 reads its `views`/`percent`
  convention: `None` means "no day-7 snapshot yet", never `0`.

- [ ] **Step 1: Write the failing tests**

Append to `shorts-factory/tests/test_dashboard.py`:

```python
def test_clips_page_lists_newest_first(client):
    reply = client.get("/")
    assert reply.status_code == 200
    body = reply.text
    assert "หัวข้อที่ถูกทิ้ง" in body
    assert "ทำไม container กิน RAM" in body
    assert body.index("หัวข้อที่ถูกทิ้ง") < body.index("ทำไม container กิน RAM")


def test_clips_page_shows_day7_numbers(client):
    body = client.get("/").text
    assert "182" in body      # views from the day-7 snapshot
    assert "41.2" in body     # its retention percent


def test_clips_page_survives_a_broken_manifest(client, data_dir):
    (data_dir / "clips" / "broken.json").write_text("{ not json", encoding="utf-8")
    assert client.get("/").status_code == 200
```

- [ ] **Step 2: Run them and watch them fail**

```bash
cd shorts-factory && python -m pytest tests/test_dashboard.py -v
```

Expected: the three new tests fail with `404` (no route yet).

- [ ] **Step 3: Implement**

Add to `shorts-factory/app/dashboard.py` — imports at the top:

```python
from fastapi import Request
from fastapi.responses import HTMLResponse

from app import analytics, experiment, history, manifest
```

and the route:

```python
def _row(record: dict) -> dict:
    """One Clip as the list shows it. `views`/`percent` are None until day 7."""
    snapshot = manifest.day7(record) or {}
    return {
        "id": record.get("id", ""),
        "created_at": record.get("created_at", ""),
        "topic": record.get("topic", ""),
        "variant": record.get("variant"),
        "explore": bool(record.get("explore")),
        "outcome": record.get("outcome", ""),
        "published": bool(record.get("published")),
        "video_id": record.get("video_id"),
        "views": snapshot.get("views"),
        "percent": snapshot.get("percent"),
    }


@app.get("/", response_class=HTMLResponse)
def clips(request: Request):
    records = manifest.load_all()
    rows = [_row(r) for r in reversed(records)]   # load_all is chronological
    return TEMPLATES.TemplateResponse(request, "clips.html", {
        "rows": rows, "total": len(records), "gate": analytics.gate_note(),
    })
```

Create `shorts-factory/app/templates/clips.html`:

```html
{% extends "base.html" %}
{% block content %}
<p class="muted">{{ total }} คลิปในบันทึก</p>
<table>
  <tr><th>เมื่อ</th><th>หัวข้อ</th><th>variant</th><th>ผล</th><th>views</th><th>ดูจนจบ</th></tr>
  {% for row in rows %}
  <tr>
    <td class="muted">{{ row.created_at[:16].replace("T", " ") }}</td>
    <td><a href="/clip/{{ row.id }}">{{ row.topic or "(ไม่มีหัวข้อ)" }}</a></td>
    <td>
      {% if row.explore %}<span class="pill">explore</span>
      {% elif row.variant %}<span class="pill">{{ row.variant }}</span>
      {% else %}<span class="muted">—</span>{% endif %}
    </td>
    <td>{{ row.outcome }}{% if row.published %} · อัปแล้ว{% endif %}</td>
    <td>{% if row.views is none %}<span class="muted">—</span>{% else %}{{ row.views }}{% endif %}</td>
    <td>{% if row.percent is none %}<span class="muted">—</span>{% else %}{{ "%.1f"|format(row.percent) }}%{% endif %}</td>
  </tr>
  {% endfor %}
</table>
{% endblock %}
```

`manifest.load_all()` already logs and skips a Manifest it cannot parse, which
is what makes the broken-file test pass — do not add a second try/except.

- [ ] **Step 4: Run the tests**

```bash
cd shorts-factory && python -m pytest tests/test_dashboard.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add shorts-factory/app/dashboard.py shorts-factory/app/templates/clips.html shorts-factory/tests/test_dashboard.py
git commit -m "feat(shorts-factory): dashboard clip list with day-7 figures"
```

---

## Task 5: `/clip/{clip_id}` — one Manifest in full

**Files:**
- Modify: `shorts-factory/app/dashboard.py`
- Create: `shorts-factory/app/templates/clip.html`
- Modify: `shorts-factory/tests/test_dashboard.py`

**Interfaces:**
- Consumes: `manifest.load(clip_id)`.
- Produces: nothing later tasks call.

- [ ] **Step 1: Write the failing tests**

Append to `shorts-factory/tests/test_dashboard.py`:

```python
def test_clip_page_shows_every_draft_and_the_snapshots(client):
    body = client.get("/clip/20260801-120000-000").text
    assert "RAM หายไปไหน" in body       # the draft's title
    assert "การ์ดหนึ่ง" in body          # the card narration
    assert "182" in body                # the snapshot row
    assert "vid1" in body               # the YouTube link


def test_clip_page_of_a_drafting_manifest_is_not_an_error(client):
    assert client.get("/clip/20260802-120000-000").status_code == 200


def test_unknown_clip_is_a_404_page_not_a_traceback(client):
    reply = client.get("/clip/nope")
    assert reply.status_code == 404
    assert "ไม่พบ" in reply.text
```

- [ ] **Step 2: Run them and watch them fail**

```bash
cd shorts-factory && python -m pytest tests/test_dashboard.py -v
```

Expected: three failures, all `404` with no Thai body.

- [ ] **Step 3: Implement**

Add to `shorts-factory/app/dashboard.py`:

```python
@app.get("/clip/{clip_id}", response_class=HTMLResponse)
def clip(request: Request, clip_id: str):
    # A Manifest id is a timestamp stem; refusing anything else keeps a path
    # like ../../etc/passwd from ever reaching manifest.load().
    record = manifest.load(clip_id) if clip_id.replace("-", "").isalnum() else None
    if record is None:
        return TEMPLATES.TemplateResponse(
            request, "clip.html", {"record": None, "gate": None}, status_code=404
        )
    return TEMPLATES.TemplateResponse(request, "clip.html", {
        "record": record,
        "drafts": record.get("scripts") or [],
        "cards": (record.get("render") or {}).get("cards") or [],
        "snapshots": record.get("snapshots") or [],
        "gate": analytics.gate_note(),
    })
```

Create `shorts-factory/app/templates/clip.html`:

```html
{% extends "base.html" %}
{% block content %}
{% if not record %}
  <p class="warn">ไม่พบคลิปนี้</p>
{% else %}
<h1>{{ record.topic or "(ไม่มีหัวข้อ)" }}</h1>
<p class="muted">
  {{ record.id }} · {{ record.created_at }} · {{ record.outcome }}
  {% if record.variant %} · <span class="pill">{{ record.variant }}</span>{% endif %}
  {% if record.explore %} · <span class="pill">explore</span>{% endif %}
  {% if record.video_id %} · <a href="https://youtu.be/{{ record.video_id }}">{{ record.video_id }}</a>{% endif %}
</p>

{% if snapshots %}
<h2>ตัวเลขรายวัน</h2>
<table>
  <tr><th>วันที่</th><th>อายุ (วัน)</th><th>views</th><th>ดูจนจบ</th></tr>
  {% for s in snapshots %}
  <tr><td>{{ s.date }}</td><td>{{ s.age_days }}</td><td>{{ s.views }}</td>
      <td>{% if s.percent is none %}—{% else %}{{ "%.1f"|format(s.percent) }}%{% endif %}</td></tr>
  {% endfor %}
</table>
{% endif %}

{% if cards %}
<h2>การ์ดที่เรนเดอร์</h2>
<table>
  <tr><th>#</th><th>เริ่มวินาทีที่</th></tr>
  {% for c in cards %}<tr><td>{{ loop.index0 }}</td><td>{{ "%.2f"|format(c.start or 0) }}</td></tr>{% endfor %}
</table>
{% endif %}

<h2>สคริปต์ทุกรอบ ({{ drafts|length }})</h2>
{% for draft in drafts %}
<div class="card">
  <p class="muted">รอบที่ {{ loop.index }} · {{ draft.at }}</p>
  <p><strong>{{ draft.script.title or "(ไม่มีชื่อ)" }}</strong>
     {% if draft.script.category %}<span class="pill">{{ draft.script.category }}</span>{% endif %}</p>
  {% for card in draft.script.cards or [] %}
    <p>{{ card.narration or "" }}
       {% if card.spoken and card.spoken != card.narration %}
         <br><span class="muted">🗣 {{ card.spoken }}</span>{% endif %}</p>
  {% endfor %}
</div>
{% else %}
<p class="muted">ยังไม่มีสคริปต์ในบันทึกนี้</p>
{% endfor %}

{% if record.storyboard %}
<h2>storyboard</h2>
<div class="card"><pre>{{ record.storyboard | tojson(indent=1) }}</pre></div>
{% endif %}
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Run the tests**

```bash
cd shorts-factory && python -m pytest tests/test_dashboard.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add shorts-factory/app/dashboard.py shorts-factory/app/templates/clip.html shorts-factory/tests/test_dashboard.py
git commit -m "feat(shorts-factory): dashboard clip detail page"
```

---

## Task 6: `/experiment` and `/now`

**Files:**
- Modify: `shorts-factory/app/dashboard.py`
- Create: `shorts-factory/app/templates/experiment.html`, `shorts-factory/app/templates/now.html`
- Modify: `shorts-factory/tests/test_dashboard.py`

**Interfaces:**
- Consumes: `experiment.tally`, `experiment.verdict`, `experiment.by_category`,
  `experiment.VARIANTS`, `history.load`.
- Produces: nothing later tasks call.

- [ ] **Step 1: Write the failing tests**

Append to `shorts-factory/tests/test_dashboard.py`:

```python
from statistics import median


def test_experiment_page_shows_both_arms_and_a_verdict(client):
    from app import experiment
    body = client.get("/experiment").text
    for name in experiment.VARIANTS:
        assert name in body
    assert "สรุปไม่ได้" in body     # two clips is far below the threshold


def test_now_page_reads_state_and_say(client):
    body = client.get("/now").text
    assert "idle" in body
    assert "ไทย" in body            # the say.json substitution


def test_now_page_without_state_file(client, data_dir):
    (data_dir / "state.json").unlink()
    reply = client.get("/now")
    assert reply.status_code == 200
```

- [ ] **Step 2: Run them and watch them fail**

```bash
cd shorts-factory && python -m pytest tests/test_dashboard.py -v
```

Expected: three failures, `404`.

- [ ] **Step 3: Implement**

Add to `shorts-factory/app/dashboard.py`:

```python
import json
from statistics import median

DATA = Path(os.environ.get("DATA_DIR", "/data"))


@app.get("/experiment", response_class=HTMLResponse)
def experiments(request: Request):
    records = manifest.load_all()
    counts = experiment.tally(records)
    arms = {
        name: dict(data, median=median(data["percents"]) if data["percents"] else None)
        for name, data in counts.items()
    }
    return TEMPLATES.TemplateResponse(request, "experiment.html", {
        "factor": experiment.FACTOR,
        "arms": arms,
        "clauses": experiment.VARIANTS,
        "verdict": experiment.verdict(counts),
        "categories": experiment.by_category(records),
        "gate": analytics.gate_note(),
    })


def _say() -> dict:
    """The pronunciation overrides the bot applies when it speaks.

    Read here rather than through `render.say_as()`: it is a plain JSON file,
    not a computed figure, and importing app.render would pull Pillow and
    edge-tts into the one process reachable from the LAN.
    """
    try:
        return json.loads((DATA / "say.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _state() -> dict:
    """The bot's state.json, or an empty one. A half-written file is not fatal."""
    try:
        return json.loads((DATA / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@app.get("/now", response_class=HTMLResponse)
def now(request: Request):
    state = _state()
    return TEMPLATES.TemplateResponse(request, "now.html", {
        "state": state,
        # `script` is the whole Script being reviewed and `suggested` a topic
        # list; both are pages of JSON that belong on /clip, not here.
        "summary": {k: v for k, v in state.items() if k not in {"script", "suggested"}},
        "say": _say(),
        "uploads": list(reversed(history.load()))[:20],
        "gate": analytics.gate_note(),
    })
```

`DATA` must be read at import time from the same env var the bot's modules use,
so the test fixture's `importlib.reload(dashboard)` picks up `tmp_path`.

Create `shorts-factory/app/templates/experiment.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1>การทดลอง: {{ factor }}</h1>
<p class="warn">{{ verdict }}</p>
<table>
  <tr><th>arm</th><th>คลิป</th><th>ทิ้ง</th><th>ล้มเหลว</th><th>views</th><th>median ดูจนจบ</th></tr>
  {% for name, data in arms.items() %}
  <tr><td>{{ name }}</td><td>{{ data.clips }}</td><td>{{ data.discarded }}</td>
      <td>{{ data.failed }}</td><td>{{ data.views }}</td>
      <td>{% if data.median is none %}<span class="muted">—</span>{% else %}{{ "%.1f"|format(data.median) }}%{% endif %}</td></tr>
  {% endfor %}
</table>

<h2>ประโยคที่ต่อท้าย prompt</h2>
<div class="grid">
  {% for name, clause in clauses.items() %}
  <div class="card"><p><strong>{{ name }}</strong></p><pre>{{ clause }}</pre></div>
  {% endfor %}
</div>

<h2>ตามหมวด <span class="muted">(สังเกตการณ์ ไม่ใช่การทดลอง — คนเลือกหัวข้อเอง)</span></h2>
<table>
  <tr><th>หมวด</th><th>คลิป</th><th>มาจาก /trends</th><th>views</th></tr>
  {% for name, data in categories.items() %}
  <tr><td>{{ name }}</td><td>{{ data.clips }}</td><td>{{ data.trend }}</td><td>{{ data.views }}</td></tr>
  {% endfor %}
</table>
{% endblock %}
```

Create `shorts-factory/app/templates/now.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1>สถานะตอนนี้</h1>
<table>
  {% for key, value in summary.items() %}
  <tr><th>{{ key }}</th><td><pre>{{ value | tojson(indent=1) if value is mapping else value }}</pre></td></tr>
  {% else %}
  <tr><td class="muted">ยังไม่มี state.json</td></tr>
  {% endfor %}
</table>

<h2>คำอ่านที่ตั้งไว้ ({{ say|length }})</h2>
<table>
  <tr><th>ที่โมเดลเขียน</th><th>ที่ให้อ่าน</th></tr>
  {% for wrong, right in say.items() %}<tr><td>{{ wrong }}</td><td>{{ right }}</td></tr>{% endfor %}
</table>

<h2>อัปล่าสุด</h2>
<table>
  <tr><th>เมื่อ</th><th>ชื่อ</th></tr>
  {% for entry in uploads %}
  <tr><td class="muted">{{ entry.uploaded_at[:16].replace("T", " ") }}</td>
      <td><a href="https://youtu.be/{{ entry.video_id }}">{{ entry.title }}</a></td></tr>
  {% endfor %}
</table>
{% endblock %}
```

- [ ] **Step 4: Run the whole file**

```bash
cd shorts-factory && python -m pytest tests/test_dashboard.py -v
```

Expected: 11 passed. `test_no_route_can_write` must still pass — if a route was
added without an explicit `@app.get`, this is where it shows.

- [ ] **Step 5: Commit**

```bash
git add shorts-factory/app/dashboard.py shorts-factory/app/templates/experiment.html shorts-factory/app/templates/now.html shorts-factory/tests/test_dashboard.py
git commit -m "feat(shorts-factory): dashboard experiment and live-state pages"
```

---

## Task 7: nginx sidecar and compose services

**Files:**
- Create: `shorts-factory/nginx/nginx.conf`
- Modify: `shorts-factory/docker-compose.yml`
- Modify: `shorts-factory/secrets.manifest.yaml` (comment only)

**Interfaces:**
- Consumes: the app listening on `0.0.0.0:8000` from Task 2.
- Produces: `http://<NAS_HOST>:5069` behind basic auth.

- [ ] **Step 1: Write the nginx config**

Create `shorts-factory/nginx/nginx.conf` (modelled on `ops-bot/nginx/nginx.conf`
— read that file first and match its style):

```nginx
server {
    listen 80;
    server_name _;

    # Every path is behind basic auth. Unlike ops-bot there is no webhook that
    # cannot send credentials, so there is no exception to make.
    auth_basic "shorts-factory";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://shorts-factory-dashboard:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

- [ ] **Step 2: Add the services**

In `shorts-factory/docker-compose.yml`, add two services after the existing
`shorts-factory` service and **above** the `volumes:` block. Do not touch the
existing service. Keep `volumes:` as the last top-level key — a second
top-level `volumes:` key would silently win and drop the first.

```yaml
  # The dashboard is a second process from the same image, with /data mounted
  # read-only: it reads the Manifests the bot writes and can never write back.
  # See docs/adr/0007. The bot above still publishes no port.
  shorts-factory-dashboard:
    build: .
    container_name: shorts-factory-dashboard
    restart: unless-stopped
    command: ["python", "-m", "app.dashboard"]
    # No `env_file: .env` on purpose. This is the only LAN-reachable process in
    # the stack and it needs no credential: the modules it imports read
    # DATA_DIR and nothing else, and `youtube.configured()` reads its env at
    # call time, which never happens here. Without the bot token and the
    # YouTube refresh token, this container cannot act even if it is reached.
    environment:
      - TZ=Asia/Bangkok
      - DATA_DIR=/data
    expose:
      - "8000"
    volumes:
      - shorts_factory_data:/data:ro
    mem_limit: 256m
    depends_on:
      - shorts-factory

  nginx:
    image: nginx:alpine
    container_name: shorts-factory-nginx
    restart: unless-stopped
    ports:
      - "5069:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./nginx/.htpasswd:/etc/nginx/.htpasswd:ro
    environment:
      - TZ=Asia/Bangkok
    mem_limit: 64m
    depends_on:
      - shorts-factory-dashboard
```

- [ ] **Step 3: Verify the compose file parses and says what you meant**

```bash
cd shorts-factory && docker compose config | grep -E "container_name|:ro|5069|mem_limit|cpus|TELEGRAM|MIMO|YOUTUBE"
```

Expected: three `container_name` lines, `shorts_factory_data:/data:ro` under
the dashboard only, `5069:80` on nginx, three `mem_limit` values, and **no
`cpus`** anywhere. No `TELEGRAM_*`/`MIMO_*`/`YOUTUBE_*` may appear under
`shorts-factory-dashboard` — if they do, `env_file` crept back in. Confirm the
bot service still has no `ports:`.

Requires `.env` from Task 0. If this errors with `env file ... not found`, go
back and run `make secrets`.

- [ ] **Step 4: Note the vault path in the secrets manifest**

Add to the top of `shorts-factory/secrets.manifest.yaml`, above `env:`:

```yaml
# The dashboard needs no app secret: auth lives in nginx/.htpasswd, generated
# at setup time from the vault creds stacks.shorts_factory.dashboard.*
```

- [ ] **Step 5: Confirm the dashboard still imports without the bot's env**

```bash
cd shorts-factory && docker compose build shorts-factory-dashboard \
  && docker compose run --rm --entrypoint python shorts-factory-dashboard -c "from app import dashboard; print('import ok')"
```

Expected: `import ok`. A failure here means some module the dashboard imports
needs a credential at import time — report it rather than adding `env_file`
back.

- [ ] **Step 6: Commit**

```bash
git add shorts-factory/nginx/nginx.conf shorts-factory/docker-compose.yml shorts-factory/secrets.manifest.yaml
git status --short   # nginx/.htpasswd must NOT appear
git commit -m "feat(shorts-factory): nginx sidecar and dashboard service on 5069"
```

---

## Task 8: Documentation and ADR 0007

**Files:**
- Create: `docs/adr/0007-dashboard-is-a-separate-read-only-container.md`
- Modify: `docs/adr/0002-shorts-factory-has-no-http-surface.md`
- Modify: `shorts-factory/README.md`, `shorts-factory/.notes/00_INDEX.md`,
  `shorts-factory/.notes/daily_log.md`, root `CLAUDE.md`, root `README.md`

**Interfaces:** none.

- [ ] **Step 1: Write ADR 0007**

Create `docs/adr/0007-dashboard-is-a-separate-read-only-container.md`. Read
`docs/adr/0002` and `docs/adr/0005` first and match their voice: prose, no
Status/Context/Decision headings, one screenful. It must say:

- the bot process is still Telegram-only and still publishes no port; what
  gained an HTTP surface is a second container
- `/data` is mounted `:ro` **and** the app declares no non-GET route, with a
  test asserting the second — two independent guards, so turning the dashboard
  into a control panel takes a deliberate removal
- that it carries no credential at all: no `env_file`, so the bot token and the
  YouTube refresh token are not in the one process reachable from the LAN
- why it shares the bot's image: importing `manifest`/`experiment`/`analytics`
  means the browser and Telegram can never quote different numbers
- why uvicorn is not inside `main.py`: the poll loop is inline and Pillow card
  drawing is in-process CPU, so an HTTP request would block for a whole render
- what stays in Telegram: script review, render, `/say`, upload. The dashboard
  reads; the human still decides on the phone
- that ADR 0002 is amended, not withdrawn

- [ ] **Step 2: Point 0002 at it**

Append one line to `docs/adr/0002-shorts-factory-has-no-http-surface.md`:

```markdown

**Amended 2026-09-01 by `docs/adr/0007`:** the dashboard was built. The bot
process is still portless and Telegram-only; the HTTP surface belongs to a
separate read-only container behind nginx basic auth on 5069.
```

- [ ] **Step 3: Update the stack README**

In `shorts-factory/README.md`, add a Dashboard section covering: the URL shape
`http://<NAS_HOST>:5069`, basic auth from the vault, the four pages and what
each answers, that it is read-only by mount and by route, and the setup command:

```bash
htpasswd -cB shorts-factory/nginx/.htpasswd <username>   # gitignored; use the vault password
```

- [ ] **Step 4: Update the root docs**

In the root `CLAUDE.md` stacks table, edit the `shorts-factory/` row: change the
port cell from `— / —` to `5069 (dashboard) / —` and append to the description:

> **Dashboard read-only ที่ 5069** (`app/dashboard.py` + nginx sidecar, ADR 0007):
> คอนเทนเนอร์แยกจากบอท อิมเมจเดียวกัน `command` ต่างกัน mount `/data:ro` — บอทเองยังไม่มีพอร์ต
> ตาม ADR 0002. หน้า `/` ลิสต์คลิปทุกอันพร้อมตัวเลข day-7, `/clip/{id}` manifest เต็มรวม draft
> ที่กดทิ้ง, `/experiment` สอง arm + verdict, `/now` state.json + say.json. **ไม่มี route
> ที่ไม่ใช่ GET** มีเทสต์ยืน — สั่งงานบอทยังต้องทำใน Telegram อย่างเดียว

Add the same port to the root `README.md` wherever ports are listed (find it
first: `grep -n "5070\|5069" README.md`).

- [ ] **Step 5: Update the stack notes**

Append to `shorts-factory/.notes/daily_log.md` a dated entry for 2026-09-01
describing what was built and why. Add a Dashboard bullet to the "Shape"
section of `shorts-factory/.notes/00_INDEX.md`, and remove or amend anything
there that claims the stack has no HTTP surface. **Never write to the root
`.notes/`.**

- [ ] **Step 6: Commit**

```bash
git add docs/adr/0007-dashboard-is-a-separate-read-only-container.md docs/adr/0002-shorts-factory-has-no-http-surface.md shorts-factory/README.md shorts-factory/.notes/ CLAUDE.md README.md
git commit -m "docs(shorts-factory): ADR 0007 and dashboard docs"
```

---

## Task 9: Build, deploy, verify on the NAS

**Files:** none committed; `shorts-factory/nginx/.htpasswd` is created locally.

This task needs the NAS and the vault. If either is unavailable, stop and report
— do not fake the verification.

- [ ] **Step 1: Confirm Task 0's artefacts are still in place**

```bash
cd /Users/peerawat.ujaiyen/MyCode/centralized-nas-container-management
test -s shorts-factory/.env && test -s shorts-factory/nginx/.htpasswd && echo "ready"
git status --short   # neither file may appear
```

- [ ] **Step 2: Run the full test suite**

```bash
cd shorts-factory && python -m pytest tests/ -v
```

Expected: everything passes, including the pre-existing tests. A failure in a
test you did not touch means an import-time change broke the bot — fix it before
deploying.

- [ ] **Step 3: Deploy**

```bash
cd /Users/peerawat.ujaiyen/MyCode/centralized-nas-container-management
./scripts/deploy.sh -s shorts-factory -y
```

`-s` selects the stack — a bare positional argument is rejected as an unknown
option, and omitting `-s` drops into an interactive prompt whose "all" answer
restarts every stack on the NAS, secretary included. `-y` is mandatory too:
without a TTY the upload is skipped silently, the script exits 0, and the build
uses the stale remote Dockerfile.

Before running it, check the host has headroom and the bot is not mid-render —
this adds 320MB of limits to a box that OOM'd on 2026-08-19:

```bash
ssh -p 2222 <NAS_USER>@<NAS_HOST> "free -m"
ssh -p 2222 <NAS_USER>@<NAS_HOST> "bash -lc 'sudo -n /usr/local/bin/docker exec shorts-factory cat /data/state.json'" | python3 -m json.tool | grep -E '"mode"|"parked"'
```

`mode` must be `idle`. A parked Clip survives a restart (it lives in
state.json); a render in flight does not.

- [ ] **Step 4: Verify on the NAS**

```bash
ssh -p 2222 <NAS_USER>@<NAS_HOST> "bash -lc 'sudo -n /usr/local/bin/docker ps --filter name=shorts-factory --format \"{{.Names}} {{.Status}} {{.Ports}}\"'"
```

Expected: `shorts-factory` (no ports), `shorts-factory-dashboard` (no published
ports), `shorts-factory-nginx` with `0.0.0.0:5069->80/tcp`, all Up.

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://<NAS_HOST>:5069/            # expect 401
curl -s -u <user>:<password> http://<NAS_HOST>:5069/healthz                 # expect {"ok":true}
curl -s -u <user>:<password> http://<NAS_HOST>:5069/ | head -40             # expect the clip table
```

If `/` returns 401 with correct credentials, the `.htpasswd` permissions are
wrong — `deploy.sh` chmods `*/nginx/.htpasswd` to 644 after upload; check it ran.

- [ ] **Step 5: Confirm the mount really is read-only**

```bash
ssh -p 2222 <NAS_USER>@<NAS_HOST> "bash -lc 'sudo -n /usr/local/bin/docker exec shorts-factory-dashboard touch /data/nope'"
```

Expected: `touch: cannot touch '/data/nope': Read-only file system`. Anything
else means the `:ro` did not take — stop and fix the compose file.

- [ ] **Step 6: Confirm the bot is unharmed**

Send a message in the Telegram chat and confirm the bot answers. The dashboard
must have changed nothing about it.

- [ ] **Step 7: Record the result**

Append the verification output (redacting host, user and password) to
`shorts-factory/.notes/daily_log.md` and commit:

```bash
git add shorts-factory/.notes/daily_log.md
git commit -m "docs(shorts-factory): record dashboard deploy verification"
```

---

## Notes for whoever executes this

- The two riskiest steps are Task 7 Step 3 (a YAML block inserted above an
  existing same-level key is silently ignored — that is why the step greps
  `docker compose config` rather than trusting the edit) and Task 9 Step 6 (a
  `:ro` that did not take looks exactly like one that did until something
  writes).
- If a route needs data that no existing module exposes, **do not add a function
  to the bot's modules.** Shape it inside `dashboard.py`. The bot's modules stay
  untouched by this feature.
- The dashboard tests run on a slim venv, because this workstation is Python
  3.9.6 with no Docker daemon and `pillow==12.3.0` has no wheel for it:
  `python3 -m venv /tmp/sf-venv && /tmp/sf-venv/bin/pip install fastapi==0.115.6 jinja2==3.1.5 httpx==0.28.1 pytest==8.4.1`
  then `cd shorts-factory && /tmp/sf-venv/bin/python -m pytest tests/test_dashboard.py -v`.
  The pre-existing `tests/test_shorts_factory.py` still needs the image and is
  run on the NAS at Task 9.
- `python -m pytest` from `shorts-factory/` is the only way to run the tests;
  the package is imported as `app.*` and relies on that working directory.
