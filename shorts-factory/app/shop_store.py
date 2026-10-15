"""Durable Shop records. This module deliberately has no rendering imports.

Every user edit uses an expected job revision. Worker validation is attached to
an immutable plan version or asset ID, so a late result cannot approve new input.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class Invalid(ValueError):
    pass


class Conflict(Invalid):
    pass


class NotFound(Invalid):
    pass


def _id():
    return uuid.uuid4().hex


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Store:
    def __init__(self, root: Path, media_root: Path | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.media_root = Path(media_root) if media_root else self.root
        self.assets_dir = self.media_root / "assets"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "shop.sqlite3"
        with self._tx() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS renders (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, fingerprint TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, dedupe TEXT UNIQUE NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS asset_job ON assets(job_id);
                CREATE INDEX IF NOT EXISTS render_job ON renders(job_id);
            """)

    @contextmanager
    def _tx(self):
        db = sqlite3.connect(self.db, timeout=30, isolation_level=None)
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
            if db.in_transaction:
                db.commit()
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def _get(self, db, table, identity):
        row = db.execute(f"SELECT body FROM {table} WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise NotFound(f"{table[:-1]} not found")
        return json.loads(row[0])

    def _save(self, db, table, value):
        db.execute(f"UPDATE {table} SET body=? WHERE id=?", (_json(value), value["id"]))

    def _job(self, db, job_id, revision=None):
        job = self._get(db, "jobs", job_id)
        if revision is not None and (type(revision) is not int or revision != job["revision"]):
            raise Conflict("job revision changed; reload before saving")
        return job

    def _touch(self, db, job):
        job["revision"] += 1
        job["updated_at"] = time.time()
        self._save(db, "jobs", job)
        return job

    def _invalidate(self, job):
        job["plan_approved_at"] = None
        job["final_approved_render_id"] = None
        job["validated_plan_version"] = None
        job["plan_error"] = None
        for scene in (job.get("plan") or {}).get("scenes", []):
            scene["accepted_at"] = None
        job["status"] = "draft"

    def _fields(self, data):
        fields = {k: data[k] for k in ("name", "brief", "destination", "current_price", "old_price", "affiliate_link") if k in data}
        for key, value in fields.items():
            if not isinstance(value, str) or len(value) > (10000 if key == "brief" else 2000):
                raise Invalid(f"invalid {key}")
        if "name" in fields and not fields["name"].strip():
            raise Invalid("name is required")
        if "destination" in fields and fields["destination"] not in ("shopee", "facebook", "youtube"):
            raise Invalid("invalid destination")
        if fields.get("affiliate_link") and not fields["affiliate_link"].startswith(("https://", "http://")):
            raise Invalid("affiliate link must be an HTTP URL")
        return fields

    def create_job(self, data: dict) -> dict:
        fields = self._fields(data)
        if not fields.get("name"):
            raise Invalid("name is required")
        now = time.time()
        job = {"id": _id(), "revision": 1, "created_at": now, "updated_at": now,
               "name": "", "brief": "", "destination": "shopee", "current_price": "", "old_price": "", "affiliate_link": "",
               "references": [], "plan": None, "plan_version": 0, "plan_approved_at": None,
               "validated_plan_version": None, "plan_error": None, "generation_error": None,
               "notification_error": None, "notification_errors": {}, "status": "draft", "final_approved_render_id": None, **fields}
        with self._tx() as db:
            db.execute("INSERT INTO jobs VALUES (?,?)", (job["id"], _json(job)))
        return job

    def get_job(self, job_id: str) -> dict:
        with self._tx() as db:
            return self._job(db, job_id)

    def list_jobs(self) -> list[dict]:
        with self._tx() as db:
            return sorted((json.loads(r[0]) for r in db.execute("SELECT body FROM jobs")), key=lambda j: j["updated_at"], reverse=True)

    def update_job(self, job_id: str, expected_revision: int, data: dict) -> dict:
        fields = self._fields(data)
        with self._tx() as db:
            job = self._job(db, job_id, expected_revision)
            job.update(fields)
            if job.get("plan"):
                job["plan_version"] += 1
            self._invalidate(job)
            return self._touch(db, job)

    def _enqueue(self, db, kind, payload, dedupe):
        row = db.execute("SELECT body FROM commands WHERE dedupe=?", (dedupe,)).fetchone()
        if row:
            return json.loads(row[0])
        command = {"id": _id(), "kind": kind, "payload": payload, "status": "queued", "attempts": 0,
                   "created_at": time.time(), "owner": None, "lease_until": None, "error": None}
        db.execute("INSERT INTO commands VALUES (?,?,?)", (command["id"], dedupe, _json(command)))
        return command

    def request_plan(self, job_id: str, expected_revision: int) -> dict:
        with self._tx() as db:
            job = self._job(db, job_id, expected_revision)
            if not job["references"]:
                raise Invalid("upload at least one reference photo")
            command = self._enqueue(db, "generate_plan", {"job_id": job_id, "revision": job["revision"]}, f"plan:{job_id}:{job['revision']}")
            if command["status"] == "failed":
                command.update(status="queued", attempts=0, error=None)
                self._save(db, "commands", command)
            job["generation_status"] = command["status"]
            job["generation_error"] = None
            self._save(db, "jobs", job)
            return command

    def save_plan(self, job_id: str, expected_revision: int, plan: dict, *, command_id: str | None = None, owner: str | None = None) -> dict:
        if not isinstance(plan, dict) or len(_json(plan)) > 100000:
            raise Invalid("invalid plan")
        plan = json.loads(_json(plan))
        scenes = plan.get("scenes")
        if not isinstance(scenes, list) or not 3 <= len(scenes) <= 6:
            raise Invalid("plan needs 3-6 scenes")
        seen = set()
        with self._tx() as db:
            self._fence(db, command_id, owner, job_id=job_id)
            job = self._job(db, job_id, expected_revision)
            for scene in scenes:
                if not isinstance(scene, dict):
                    raise Invalid("invalid scene")
                identity = scene.get("id")
                if not isinstance(identity, str) or not identity or len(identity) > 100 or identity in seen:
                    raise Invalid("scene IDs must be unique strings")
                seen.add(identity)
                if scene.get("source") not in ("flow", "real", "still") or scene.get("fit", "crop") not in ("crop", "contain"):
                    raise Invalid("invalid scene source or fit")
                if not isinstance(scene.get("narration", ""), str) or not isinstance(scene.get("lines", []), list):
                    raise Invalid("invalid narration or lines")
                if any(not isinstance(line, str) for line in scene.get("lines", [])):
                    raise Invalid("scene lines must be strings")
                duration = scene.get("required_duration", 0)
                if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= 60:
                    raise Invalid("scene duration must be a number between 0 and 60 seconds")
                reference = scene.get("reference_id")
                if reference and reference not in job["references"]:
                    raise Invalid("reference does not belong to job")
                # Client edits cannot forge worker validation or acceptance.
                previous = next((s for s in (job.get("plan") or {}).get("scenes", [])
                                 if s["id"] == identity and s["source"] == scene["source"]), {})
                scene.update(accepted_at=None, media_id=previous.get("media_id"), pending_media_id=previous.get("pending_media_id"))
                scene.setdefault("fit", "crop")
                if scene["source"] == "still" and not scene["media_id"]:
                    scene["media_id"] = reference
            job["plan"] = plan
            job["generation_status"] = "done"
            job["generation_error"] = None
            job["plan_version"] += 1
            self._invalidate(job)
            self._touch(db, job)
            self._enqueue(db, "validate_plan", {"job_id": job_id, "plan_version": job["plan_version"]}, f"validate-plan:{job_id}:{job['plan_version']}")
            return job

    def validate_plan(self, job_id: str, plan_version: int, *, valid: bool, error: str | None = None, command_id: str | None = None, owner: str | None = None) -> dict:
        with self._tx() as db:
            self._fence(db, command_id, owner, job_id=job_id)
            job = self._job(db, job_id)
            if plan_version != job["plan_version"]:
                raise Conflict("plan version changed")
            job["validated_plan_version"] = plan_version if valid else None
            job["plan_error"] = None if valid else (error or "invalid plan")
            self._save(db, "jobs", job)
            return job

    def set_generation_error(self, job_id: str, expected_revision: int, error: str | None, *, command_id: str | None = None, owner: str | None = None) -> dict:
        """Generation/provider failure must not invalidate the last good plan."""
        with self._tx() as db:
            self._fence(db, command_id, owner, job_id=job_id)
            job = self._job(db, job_id, expected_revision)
            job["generation_error"] = error
            self._save(db, "jobs", job)
            return job

    def approve_plan(self, job_id: str, expected_revision: int) -> dict:
        with self._tx() as db:
            job = self._job(db, job_id, expected_revision)
            if not job["plan"] or job["validated_plan_version"] != job["plan_version"]:
                raise Invalid("plan must pass worker validation before approval")
            if not job["references"] or any(not s.get("reference_id") for s in job["plan"]["scenes"]):
                raise Invalid("each scene needs a selected product reference")
            for reference in job["references"]:
                if self._get(db, "assets", reference)["validation"] != "valid":
                    raise Invalid("reference photo is awaiting validation or invalid")
            job["plan_approved_at"] = time.time()
            job["status"] = "waiting_for_clips"
            return self._touch(db, job)

    def add_asset(self, job_id: str, expected_revision: int, kind: str, filename: str, stream, *, scene_id: str | None = None) -> dict:
        name = str(filename).replace("\\", "/").rsplit("/", 1)[-1][:250]
        extension = Path(name).suffix.lower()
        if kind not in ("reference", "scene"):
            raise Invalid("invalid asset kind")
        allowed = (".jpg", ".jpeg", ".png", ".webp") if kind == "reference" else (".mp4", ".mov", ".jpg", ".jpeg", ".png", ".webp")
        if extension not in allowed:
            raise Invalid("unsupported file extension")
        limit = (15 if extension in (".jpg", ".jpeg", ".png", ".webp") else 100) * 1024 * 1024
        identity = _id()
        key = identity + extension
        temporary = self.assets_dir / (identity + ".upload")
        final = self.assets_dir / key
        size, digest = 0, hashlib.sha256()
        try:
            with temporary.open("xb") as output:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        raise Invalid("file exceeds upload limit")
                    digest.update(chunk)
                    output.write(chunk)
            if not size:
                raise Invalid("empty upload")
            with self._tx() as db:
                job = self._job(db, job_id, expected_revision)
                scene = None
                if kind == "reference":
                    if len(job["references"]) >= 6:
                        raise Invalid("maximum six reference photos")
                    job["references"].append(identity)
                    if job["plan"]:
                        job["plan_version"] += 1
                    self._invalidate(job)
                else:
                    scene = self._scene(job, scene_id)
                    if scene["source"] != "still" and extension not in (".mp4", ".mov"):
                        raise Invalid("video scene requires MP4 or MOV")
                    if scene["source"] == "still" and extension in (".mp4", ".mov"):
                        raise Invalid("still scene requires a photo")
                    scene["pending_media_id"] = identity
                asset = {"id": identity, "job_id": job_id, "scene_id": scene_id, "kind": kind, "name": name,
                         "key": key, "size": size, "sha256": digest.hexdigest(), "validation": "pending",
                         "metadata": {}, "error": None, "created_at": time.time()}
                os.replace(temporary, final)
                db.execute("INSERT INTO assets VALUES (?,?,?)", (identity, job_id, _json(asset)))
                self._touch(db, job)
                self._enqueue(db, "probe_asset", {"asset_id": identity, "job_id": job_id}, f"probe:{identity}")
                return asset
        except BaseException:
            temporary.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            raise

    def _scene(self, job, scene_id):
        for scene in (job.get("plan") or {}).get("scenes", []):
            if scene["id"] == scene_id:
                return scene
        raise NotFound("scene not found")

    def validate_asset(self, asset_id: str, metadata: dict, *, valid: bool, error: str | None = None, command_id: str | None = None, owner: str | None = None) -> dict:
        with self._tx() as db:
            self._fence(db, command_id, owner, asset_id=asset_id)
            asset = self._get(db, "assets", asset_id)
            asset.update(validation="valid" if valid else "invalid", metadata=metadata, error=None if valid else (error or "invalid media"))
            self._save(db, "assets", asset)
            job = self._job(db, asset["job_id"])
            if asset["kind"] == "scene":
                try:
                    scene = self._scene(job, asset["scene_id"])
                except NotFound:
                    scene = None
                if scene and scene.get("pending_media_id") == asset_id:
                    scene["pending_media_id"] = None
                    if valid:
                        scene.update(media_id=asset_id, accepted_at=None)
                        job["final_approved_render_id"] = None
                        job["status"] = "waiting_for_clips"
                    self._touch(db, job)
            return asset

    def get_asset(self, asset_id: str, job_id: str | None = None) -> dict:
        with self._tx() as db:
            asset = self._get(db, "assets", asset_id)
            if job_id is not None and asset["job_id"] != job_id:
                raise NotFound("asset not found")
            return asset

    def remove_reference(self, job_id: str, expected_revision: int, asset_id: str) -> dict:
        with self._tx() as db:
            job = self._job(db, job_id, expected_revision)
            if asset_id not in job["references"]:
                raise NotFound("reference not found")
            job["references"].remove(asset_id)
            for scene in (job.get("plan") or {}).get("scenes", []):
                if scene.get("reference_id") == asset_id:
                    scene["reference_id"] = None
                if scene.get("media_id") == asset_id:
                    scene["media_id"] = None
            job["plan_version"] += 1
            self._invalidate(job)
            return self._touch(db, job)

    def list_assets(self, job_id: str) -> list[dict]:
        with self._tx() as db:
            self._job(db, job_id)
            return [json.loads(r[0]) for r in db.execute("SELECT body FROM assets WHERE job_id=?", (job_id,))]

    def asset_path(self, asset_id: str, job_id: str | None = None) -> Path:
        asset = self.get_asset(asset_id, job_id)
        # Storage keys are generated; still defend against corrupted metadata.
        path = (self.assets_dir / asset["key"]).resolve()
        if path.parent != self.assets_dir.resolve():
            raise Invalid("invalid storage key")
        return path

    def accept_scene(self, job_id: str, expected_revision: int, scene_id: str, *, reference_matches: bool) -> dict:
        with self._tx() as db:
            job = self._job(db, job_id, expected_revision)
            if not job["plan_approved_at"]:
                raise Invalid("approve plan first")
            scene = self._scene(job, scene_id)
            if not reference_matches:
                raise Invalid("confirm media matches the product reference")
            if not scene.get("media_id") or scene.get("pending_media_id"):
                raise Invalid("scene media missing or awaiting validation")
            asset = self._get(db, "assets", scene["media_id"])
            if asset["validation"] != "valid":
                raise Invalid("scene media must pass validation")
            if scene["source"] != "still" and float(asset["metadata"].get("duration", 0)) < float(scene.get("required_duration", 0)):
                raise Invalid("scene video is shorter than requested duration")
            scene["accepted_at"] = time.time()
            job["final_approved_render_id"] = None
            job["status"] = "ready_to_render" if all(s.get("accepted_at") for s in job["plan"]["scenes"]) else "waiting_for_clips"
            return self._touch(db, job)

    def request_render(self, job_id: str, expected_revision: int, *, retry: bool = False) -> dict:
        with self._tx() as db:
            job = self._job(db, job_id, expected_revision)
            scenes = (job["plan"] or {}).get("scenes", [])
            if not job["plan_approved_at"] or not scenes or any(not s.get("accepted_at") or s.get("pending_media_id") for s in scenes):
                raise Invalid("approve plan and accept every scene before rendering")
            if not any(s["source"] in ("flow", "real") for s in scenes):
                raise Invalid("at least one accepted video scene is required")
            assets = {a: self._get(db, "assets", a) for a in set(job["references"] + [s["media_id"] for s in scenes])}
            snapshot = {**job, "assets": assets}
            content = {k: snapshot[k] for k in ("name", "brief", "destination", "current_price", "old_price", "affiliate_link", "plan", "assets", "plan_version")}
            fingerprint = hashlib.sha256(_json(content).encode()).hexdigest()
            prior = [json.loads(r[0]) for r in db.execute("SELECT body FROM renders WHERE job_id=? AND fingerprint=?", (job_id, fingerprint))]
            prior.sort(key=lambda r: r["attempt"], reverse=True)
            if prior and prior[0]["status"] != "failed":
                return prior[0]
            if prior and not retry:
                return prior[0]
            # One active render per job, including snapshots superseded by edits.
            for row in db.execute("SELECT body FROM renders WHERE job_id=?", (job_id,)):
                if json.loads(row[0])["status"] in ("pending_dispatch", "queued", "running"):
                    raise Conflict("a render is already active for this job")
            render = {"id": _id(), "job_id": job_id, "revision": job["revision"], "plan_version": job["plan_version"],
                      "snapshot": snapshot, "fingerprint": fingerprint, "attempt": (prior[0]["attempt"] + 1) if prior else 1,
                      "status": "pending_dispatch", "created_at": time.time(), "updated_at": time.time(), "error": None,
                      "outputs": {}, "approved_at": None}
            db.execute("INSERT INTO renders VALUES (?,?,?,?)", (render["id"], job_id, fingerprint, _json(render)))
            job["status"] = "pending_dispatch"
            self._save(db, "jobs", job)
            return render

    def get_render(self, render_id: str) -> dict:
        with self._tx() as db:
            return self._get(db, "renders", render_id)

    def list_renders(self, job_id: str) -> list[dict]:
        with self._tx() as db:
            self._job(db, job_id)
            return [json.loads(r[0]) for r in db.execute("SELECT body FROM renders WHERE job_id=?", (job_id,))]

    def pending_dispatches(self) -> list[dict]:
        with self._tx() as db:
            pending = []
            for (body,) in db.execute("SELECT body FROM renders"):
                render = json.loads(body)
                item = {k: render[k] for k in ("id", "job_id", "revision", "status", "attempt")}
                if render["status"] in ("pending_dispatch", "queued", "running"):
                    pending.append(item)
                elif render["status"] in ("ready", "failed"):
                    # Terminal attempts remain in the reconciliation outbox until
                    # their canonical notification is successfully delivered.
                    key = self._notification_key(render["job_id"], render["status"], render["id"])
                    row = db.execute("SELECT body FROM commands WHERE dedupe=?", (key,)).fetchone()
                    command = json.loads(row[0]) if row else None
                    if command is None or command["status"] == "failed":
                        item.update(notification_status=command["status"] if command else "missing",
                                    notification_error=command["error"] if command else None)
                        pending.append(item)
            return pending

    def start_render(self, render_id: str, expected_revision: int, idempotency_key: str) -> dict:
        if not idempotency_key or len(idempotency_key) > 200:
            raise Invalid("idempotency key is required")
        with self._tx() as db:
            render = self._get(db, "renders", render_id)
            if expected_revision != render["revision"]:
                raise Conflict("render revision differs")
            dedupe = f"start:{idempotency_key}"
            row = db.execute("SELECT body FROM commands WHERE dedupe=?", (dedupe,)).fetchone()
            if row and json.loads(row[0])["payload"]["render_id"] != render_id:
                raise Conflict("idempotency key already used for another render")
            if render["status"] == "pending_dispatch":
                render.update(status="queued", updated_at=time.time())
                self._save(db, "renders", render)
                self._enqueue(db, "render", {"render_id": render_id, "job_id": render["job_id"]}, dedupe)
                job = self._job(db, render["job_id"])
                job["status"] = "queued"
                self._save(db, "jobs", job)
            return render

    def _fence(self, db, command_id, owner, *, job_id=None, asset_id=None):
        if command_id is None and owner is None:
            return
        if not command_id or not owner:
            raise Conflict("worker command and owner are required together")
        command = self._owned(db, command_id, owner)
        if job_id and command["payload"].get("job_id") != job_id:
            raise Conflict("command owns another job")
        if asset_id and command["payload"].get("asset_id") != asset_id:
            raise Conflict("command owns another asset")

    def _owned(self, db, command_id, owner):
        command = self._get(db, "commands", command_id)
        if command["status"] != "running" or command["owner"] != owner or command["lease_until"] < time.time():
            raise Conflict("worker lease no longer owns command")
        return command

    def claim_command(self, owner: str, *, kinds: list[str] | None = None, lease_seconds: int = 120, now: float | None = None) -> dict | None:
        now = time.time() if now is None else now
        with self._tx() as db:
            for (body,) in db.execute("SELECT body FROM commands ORDER BY rowid"):
                command = json.loads(body)
                if kinds and command["kind"] not in kinds:
                    continue
                if command["status"] == "queued" or (command["status"] == "running" and command["lease_until"] < now):
                    command.update(status="running", owner=owner, lease_until=now + lease_seconds, heartbeat_at=now, attempts=command["attempts"] + 1)
                    self._save(db, "commands", command)
                    return command
        return None

    def heartbeat(self, command_id: str, owner: str, *, lease_seconds: int = 120) -> dict:
        with self._tx() as db:
            command = self._owned(db, command_id, owner)
            command.update(lease_until=time.time() + lease_seconds, heartbeat_at=time.time())
            self._save(db, "commands", command)
            return command

    def finish_command(self, command_id: str, owner: str, *, error: str | None = None, retry: bool = True) -> dict:
        with self._tx() as db:
            command = self._owned(db, command_id, owner)
            if command["kind"] == "notify" and command["attempts"] >= 3:
                retry = False
            command.update(status=("queued" if retry else "failed") if error else "done", error=error, owner=None, lease_until=None)
            self._save(db, "commands", command)
            if command["kind"] == "generate_plan":
                job = self._job(db, command["payload"]["job_id"])
                if job["revision"] == command["payload"]["revision"]:
                    job["generation_error"] = error
                    job["generation_status"] = command["status"]
                    self._save(db, "jobs", job)
            elif command["kind"] == "notify":
                job = self._job(db, command["payload"]["job_id"])
                errors = job.setdefault("notification_errors", {})
                if error:
                    errors[command_id] = error
                else:
                    errors.pop(command_id, None)
                job["notification_error"] = next(reversed(errors.values()), None)
                self._save(db, "jobs", job)
            return command

    def set_render_result(self, render_id: str, status: str, *, outputs: dict | None = None, error: str | None = None,
                          command_id: str | None = None, owner: str | None = None) -> dict:
        if status not in ("running", "ready", "failed"):
            raise Invalid("invalid render status")
        with self._tx() as db:
            if command_id is not None:
                command = self._owned(db, command_id, owner)
                if command["payload"].get("render_id") != render_id:
                    raise Conflict("command owns another render")
            render = self._get(db, "renders", render_id)
            if render["status"] in ("ready", "failed"):
                raise Conflict("render attempt already finished")
            render.update(status=status, outputs=outputs or {}, error=error, updated_at=time.time())
            self._save(db, "renders", render)
            job = self._job(db, render["job_id"])
            if job["revision"] == render["revision"]:
                job["status"] = status
                self._save(db, "jobs", job)
            return render

    def approve_render(self, job_id: str, expected_revision: int, render_id: str) -> dict:
        with self._tx() as db:
            job = self._job(db, job_id, expected_revision)
            render = self._get(db, "renders", render_id)
            if render["job_id"] != job_id or render["revision"] != expected_revision or render["status"] != "ready":
                raise Conflict("render is unavailable or outdated")
            render["approved_at"] = time.time()
            self._save(db, "renders", render)
            job["final_approved_render_id"] = render_id
            job["updated_at"] = time.time()
            self._save(db, "jobs", job)
            return job

    def _notification_key(self, job_id, milestone, event_id):
        return f"notify:{job_id}:{event_id}:{milestone}"

    def notify(self, job_id: str, milestone: str, idempotency_key: str, *, render_id: str | None = None, retry: bool = False, command_id: str | None = None, owner: str | None = None) -> dict:
        if milestone not in ("plan_ready", "waiting", "ready", "failed") or not idempotency_key or len(idempotency_key) > 200:
            raise Invalid("invalid notification request")
        with self._tx() as db:
            self._fence(db, command_id, owner, job_id=job_id)
            job = self._job(db, job_id)
            if render_id:
                render = self._get(db, "renders", render_id)
                if render["job_id"] != job_id or (milestone in ("ready", "failed") and render["status"] != milestone):
                    raise Invalid("notification does not match render status")
            event_id = render_id or f"plan-{job['plan_version']}"
            key = self._notification_key(job_id, milestone, event_id)
            command = self._enqueue(db, "notify", {"job_id": job_id, "milestone": milestone, "render_id": render_id}, key)
            # Random reconciliation keys never bypass an exhausted command.
            # An explicit retry reuses its durable identity and starts one new
            # bounded delivery cycle; worker still controls max attempts.
            if retry and command["status"] == "failed":
                command.update(status="queued", attempts=0, error=None,
                               retries=command.get("retries", 0) + 1)
                self._save(db, "commands", command)
                errors = job.setdefault("notification_errors", {})
                errors.pop(command["id"], None)
                job["notification_error"] = next(reversed(errors.values()), None)
                self._save(db, "jobs", job)
            return command

    def retry_notifications(self, job_id: str, expected_revision: int) -> dict:
        """User explicitly starts a fresh bounded delivery cycle for failed notices."""
        with self._tx() as db:
            job = self._job(db, job_id, expected_revision)
            for (body,) in db.execute("SELECT body FROM commands"):
                command = json.loads(body)
                if command["kind"] == "notify" and command["payload"].get("job_id") == job_id and command["status"] == "failed":
                    command.update(status="queued", attempts=0, error=None, retries=command.get("retries", 0) + 1)
                    self._save(db, "commands", command)
                    job.setdefault("notification_errors", {}).pop(command["id"], None)
            job["notification_error"] = next(reversed(job.get("notification_errors", {}).values()), None)
            self._save(db, "jobs", job)
            return job
