"""A window onto what the bot has already written down.

Runs as its own container from the same image as the bot, with /data mounted
read-only, and imports the bot's own modules so its figures cannot drift from
the ones Telegram reports. It defines exactly one route that writes — the
trends schedule, on its own volume — and nothing else: see docs/adr/0007 as
amended by 0009.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from statistics import median

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import (
    analytics,
    experiment,
    history,
    locales,
    manifest,
    model_choice,
    pronunciation,
    schedule,
)
from app import dashboard_view as view

HERE = Path(__file__).parent
DATA = Path(os.environ.get("DATA_DIR", "/data"))

app = FastAPI(title="shorts-factory", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
TEMPLATES = Jinja2Templates(directory=HERE / "templates")
TEMPLATES.env.filters.update(number=view.format_number,
                             datetime_display=view.format_date,
                             percent=view.format_percent)
TEMPLATES.env.globals["arm_labels"] = view.ARM_LABELS


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


def _row(record: dict, state: dict | None = None) -> dict:
    """One Clip as the list shows it. `views`/`percent` are None until day 7."""
    snapshot = manifest.day7(record) or {}
    locale = locales.get(record.get("locale"))
    scripts = record.get("scripts") or []
    script = (scripts[-1].get("script") or {}) if scripts else {}
    title = script.get("title") or record.get("topic") or "(ไม่มีหัวข้อ)"
    return {
        "id": record.get("id", ""),
        # Which channel this Clip belongs to. Manifests older than Locales
        # carry no field and are Thai (docs/adr/0008).
        "locale": locale["label"],
        "locale_code": locale["code"],
        "title": title,
        "category": script.get("category") or "",
        "cover": title[:3],
        "duration": (record.get("render") or {}).get("duration"),
        "status": view.status(record, state),
        "search": " ".join(str(value or "") for value in
                           (record.get("id"), record.get("topic"), title, script.get("category"))),
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


def _summary(rows: list[dict], locale: str = locales.DEFAULT) -> dict:
    """The four figures the list page leads with.

    All of them come from the day-7 snapshot rather than the latest one, for
    the reason `manifest.day7` gives: retention keeps moving as views accrue.
    `state.json` is deliberately not among them — the bot writes it and the
    dashboard only reads, so a stale `mode` would read as a live one.
    """
    rows = [r for r in rows if r["locale_code"] == locale]
    percents = [r["percent"] for r in rows if r["percent"] is not None]
    measured = sum(r["views"] is not None for r in rows)
    return {
        "published": len(history.video_ids(locale)),
        "gate_clips": analytics.GATE_CLIPS,
        "median": median(percents) if percents else None,
        "views": sum(r["views"] or 0 for r in rows) if measured else None,
        "total": len(rows),
        "discarded": sum(1 for r in rows if r["outcome"] == "discarded"),
        "measured": measured,
        "measured_percents": len(percents),
    }


@app.get("/", response_class=HTMLResponse)
def clips(request: Request):
    records = manifest.load_all()
    state = _state()
    rows = [_row(r, state) for r in reversed(records)]   # load_all is chronological
    stored_schedule = schedule.settings()
    channels = [{"code": code, "label": locales.get(code)["label"],
                 "summary": _summary(rows, code), "gate": analytics.gate_note(code),
                 "schedule": stored_schedule[code]}
                for code in [locales.DEFAULT] + [c for c in locales.codes() if c != locales.DEFAULT]]
    statuses = {row["status"]["key"]: dict(row["status"], label="ล้มเหลว")
                if row["status"]["key"] == "failed" else row["status"] for row in rows}
    return TEMPLATES.TemplateResponse(request, "clips.html", {
        "rows": rows,
        "total": len(records),
        "summary": _summary(rows),
        "channels": channels,
        "statuses": list(statuses.values()),
        # The filter buttons are built from what is actually on the page, so a
        # new outcome the bot starts writing appears without a code change.
        "outcomes": sorted({r["outcome"] for r in rows if r["outcome"]}),
        "gate": None,
    })


CHART = {"w": 640, "h": 160, "pad": 8}


def _chart(snapshots: list[dict]) -> dict | None:
    """Views over age, as coordinates for an inline SVG polyline.

    Drawn in the template rather than by `app.retention`: that module renders
    PNGs with Pillow, and docs/adr/0007 keeps Pillow out of the one process
    reachable from the LAN. Two points are the minimum that draws a line.
    """
    points = [(s.get("age_days") or 0, s.get("views") or 0) for s in snapshots]
    if len(points) < 2:
        return None
    w, h, pad = CHART["w"], CHART["h"], CHART["pad"]
    span = max(x for x, _ in points) - min(x for x, _ in points) or 1
    top = max(y for _, y in points) or 1
    left = min(x for x, _ in points)
    xy = [
        (pad + (x - left) / span * (w - 2 * pad), h - pad - y / top * (h - 2 * pad))
        for x, y in points
    ]
    return {
        "line": " ".join(f"{x:.1f},{y:.1f}" for x, y in xy),
        "area": f"{xy[0][0]:.1f},{h - pad} " +
                " ".join(f"{x:.1f},{y:.1f}" for x, y in xy) +
                f" {xy[-1][0]:.1f},{h - pad}",
        "dots": [{"x": round(x, 1), "y": round(y, 1)} for x, y in xy],
        "top": top,
        "first_age": min(x for x, _ in points),
        "last_age": max(x for x, _ in points),
        **CHART,
    }


@app.get("/clip/{clip_id}", response_class=HTMLResponse)
def clip(request: Request, clip_id: str):
    # A Manifest id is a timestamp stem; refusing anything else keeps a path
    # like ../../etc/passwd from ever reaching manifest.load().
    record = manifest.load(clip_id) if clip_id.replace("-", "").isalnum() else None
    if record is None:
        return TEMPLATES.TemplateResponse(
            request, "clip.html", {"record": None, "gate": None}, status_code=404
        )
    snapshots = record.get("snapshots") or []
    drafts = record.get("scripts") or []
    latest = drafts[-1] if drafts else None
    locale = locales.get(record.get("locale"))
    return TEMPLATES.TemplateResponse(request, "clip.html", {
        "record": record,
        "drafts": drafts,
        "latest": latest,
        "previous_drafts": drafts[:-1],
        "checks": pronunciation.collect(latest.get("script") or {}, locale["code"]) if latest else [],
        "sources": view.sources(record),
        "row": _row(record, _state()),
        "locale": locale,
        "cards": (record.get("render") or {}).get("cards") or [],
        "snapshots": snapshots,
        "day7": manifest.day7(record),
        "chart": _chart(snapshots),
        "gate": analytics.gate_note(locale["code"]),
    })


@app.get("/experiment", response_class=HTMLResponse)
def experiments(request: Request):
    """One section per Locale: two audiences never share a set of counters.

    Thai is always shown — it is the channel that has been running. Another
    Locale appears once it has Clips of its own, so the page reads exactly as
    it did until the second channel produces something.
    """
    records = manifest.load_all()
    sections = []
    for locale in locales.codes():
        mine = experiment.for_locale(records, locale)
        if locale != locales.DEFAULT and not mine:
            continue
        counts = experiment.tally(mine)
        gate = analytics.gate_note(locale)
        sections.append({
            "locale": locale,
            "label": locales.get(locale)["label"],
            "arms": {
                name: dict(data, median=median(data["percents"]) if data["percents"] else None)
                for name, data in counts.items()
            },
            "clauses": experiment.VARIANTS_BY_LOCALE.get(locale, experiment.VARIANTS),
            "verdict": "ยังสรุปไม่ได้ — รอให้ช่องผ่านเกณฑ์ข้อมูลก่อน" if gate else experiment.verdict(counts),
            "categories": experiment.by_category(mine),
            "gate": gate,
        })
    return TEMPLATES.TemplateResponse(request, "experiment.html", {
        "factor": experiment.FACTOR,
        "sections": sections,
        "min_clips": experiment.MIN_CLIPS,
        "min_views": experiment.MIN_VIEWS,
        "arm_labels": view.ARM_LABELS,
    })


def _say() -> dict:
    """The pronunciation overrides the bot applies when it speaks.

    Read here rather than through `render.say_as()`: it is a plain JSON file,
    not a computed figure, and importing app.render would pull Pillow and
    edge-tts into the one process reachable from the LAN.
    """
    try:
        value = json.loads((DATA / "say.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _state() -> dict:
    """The bot's state.json, or an empty one. A half-written file is not fatal."""
    try:
        value = json.loads((DATA / "state.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


# Keys worth a card of their own. The rest still appear below verbatim: the
# bot grows new keys often (`parked`, `last_auto_trends`), and a dashboard that
# only rendered the ones named here would hide every one of them.
HEADLINE = ("mode", "topic", "clip_id", "style", "parked", "auto_pick", "last_snapshot")


@app.get("/now", response_class=HTMLResponse)
def now(request: Request):
    state = _state()
    summary = {k: v for k, v in state.items() if k not in {"script", "suggested"}}
    return TEMPLATES.TemplateResponse(request, "now.html", {
        "state": state,
        # `script` is the whole Script being reviewed and `suggested` a topic
        # list; both are pages of JSON that belong on /clip, not here.
        "summary": summary,
        "headline": [(k, summary[k]) for k in HEADLINE if k in summary],
        "rest": {k: v for k, v in summary.items() if k not in HEADLINE},
        "say": _say(),
        "uploads": list(reversed(history.load()))[:20],
        "mode_label": view.MODES.get(state.get("mode"), (state.get("mode") or "ยังไม่มีสถานะ", "neutral"))[0],
        "mode_tone": view.MODES.get(state.get("mode"), ("", "neutral"))[1],
        "waits": view.waiting_jobs(state),
        "gate": None,
    })


# --- the one writing route (docs/adr/0009) -----------------------------------

def _settings_page(request: Request, stored: dict, models: dict,
                   saved: bool = False, error: str = "", status: int = 200,
                   submitted=None):
    rows = [{"code": code, "label": locales.get(code)["label"],
             "enabled": spec["enabled"], "hours": ",".join(str(h) for h in spec["hours"]),
             "minutes": spec["auto_pick_minutes"]} for code, spec in sorted(stored.items())]
    if submitted is not None:
        for row in rows:
            code = row["code"]
            row.update(enabled=bool(submitted.get(f"{code}_enabled")),
                       hours=str(submitted.get(f"{code}_hours", "")),
                       minutes=str(submitted.get(f"{code}_minutes", "")))
        models = {role: str(submitted.get(f"model_{role}", "")) for role in model_choice.ROLES}
    choices = model_choice.choices()
    return TEMPLATES.TemplateResponse(request, "settings.html", {
        "rows": rows,
        "stamps": schedule.stamps(_state()),
        "min_minutes": schedule.MIN_PICK_MINUTES,
        "max_minutes": schedule.MAX_PICK_MINUTES,
        "models": models,
        "model_choices": choices,
        "invalid_models": [name for name in models.values() if name and name not in choices],
        "catalog_at": model_choice.catalog().get("fetched_at"),
        "saved": saved,
        "error": error,
        "gate": None,
    }, status_code=status)


@app.get("/settings", response_class=HTMLResponse)
def settings_form(request: Request):
    return _settings_page(request, schedule.settings(), model_choice.stored())


@app.post("/settings", response_class=HTMLResponse)
async def settings_save(request: Request):
    """Rewrite `/config/schedule.json` and `/config/models.json`. The only
    non-GET route in this app.

    Everything the form sends is untrusted text off a LAN page behind one basic
    auth, so nothing is coerced generously: `schedule.validate()` rejects the
    whole request rather than storing the half of it that parsed, and the reply
    is the same page with the message on it.
    """
    form = await request.form()
    payload = {}
    for code in locales.codes():
        raw = str(form.get(f"{code}_hours", "")).replace(" ", "")
        payload[code] = {
            "enabled": bool(form.get(f"{code}_enabled")),
            "hours": [h for h in raw.split(",") if h],
            "auto_pick_minutes": form.get(f"{code}_minutes", "15"),
        }
    models = {role: str(form.get(f"model_{role}", "")) for role in model_choice.ROLES}
    try:
        # Both checked before either is written: one bad field stores nothing.
        schedule.validate(payload)
        model_choice.validate(models)
        stored = schedule.save(payload)
        chosen = model_choice.save(models)
    except ValueError as exc:
        # Show what they typed back, not what is on disk: a rejected form that
        # redraws itself from storage silently discards the edit.
        return _settings_page(request, schedule.settings(), model_choice.stored(),
                              error=str(exc), status=400, submitted=form)
    return _settings_page(request, stored, chosen, saved=True)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
