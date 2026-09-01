"""A window onto what the bot has already written down.

Runs as its own container from the same image as the bot, with /data mounted
read-only, and imports the bot's own modules so its figures cannot drift from
the ones Telegram reports. It defines no route that writes: see docs/adr/0007.
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

from app import analytics, experiment, history, manifest

HERE = Path(__file__).parent
DATA = Path(os.environ.get("DATA_DIR", "/data"))

app = FastAPI(title="shorts-factory", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
TEMPLATES = Jinja2Templates(directory=HERE / "templates")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


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


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
