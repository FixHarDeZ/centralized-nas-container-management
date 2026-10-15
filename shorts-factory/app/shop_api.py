"""Private Shop HTTP service, published only through authenticated nginx.

Browser mutations use a same-origin double-submit CSRF token. Automation has a
separate scoped credential and cannot bypass CSRF on the browser endpoints.
Rendering/model/media decoding belong exclusively to the worker.
"""
from __future__ import annotations

import hmac
import json
import mimetypes
import os
import secrets
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

from app.shop_affiliate import Affiliate
from app.shop_report import ReportError
from app.shop_store import Conflict, Invalid, NotFound, Store


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)


class Edit(Revision):
    name: str | None = None
    brief: str | None = None
    destination: str | None = None
    current_price: str | None = None
    old_price: str | None = None
    affiliate_link: str | None = None


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    brief: str = ""
    destination: str = "shopee"
    current_price: str = ""
    old_price: str = ""
    affiliate_link: str = ""


class PlanEdit(Revision):
    plan: dict


class Accept(Revision):
    reference_matches: bool = Field(strict=True)


class RenderRequest(Revision):
    retry: bool = Field(default=False, strict=True)


class Start(Revision):
    idempotency_key: str = Field(min_length=1, max_length=200)


class ProductInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0, strict=True)
    product_url: str | None = None
    shop_name: str | None = None
    category: str | None = None
    commission_rate: str | float | None = None
    campaign_name: str | None = None
    campaign_ends: str | None = None


class Manual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clicks: str | int | None = None
    orders: str | int | None = None
    commission: str | float | None = None


class Post(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str
    url: str = ""
    posted_on: str | None = None
    render_id: str | None = None


class PostEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str | None = None
    posted_on: str | None = None
    render_id: str | None = None
    manual: Manual | None = None


REPORT_LIMIT = 20 * 1024 * 1024


class Notification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    milestone: str
    idempotency_key: str = Field(min_length=1, max_length=200)
    render_id: str | None = None
    retry: bool = Field(default=False, strict=True)


def create_app(root: Path | None = None) -> FastAPI:
    root = Path(root) if root is not None else Path(os.environ.get("SHOP_ROOT", "/shop-data"))
    media_root = os.environ.get("SHOP_MEDIA_ROOT")
    store = Store(root, Path(media_root) if media_root else None)
    app = FastAPI(title="Shop Flow Studio", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    affiliate = Affiliate(store)
    app.state.affiliate = affiliate
    automation_token = os.environ.get("SHOP_AUTOMATION_TOKEN", "")

    def origin_for(request):
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
        if scheme not in ("http", "https"):
            return None
        return f"{scheme}://{request.headers.get('host', '')}"

    @app.middleware("http")
    async def protect(request: Request, call_next):
        path = request.url.path
        if path.startswith("/shop/automation/"):
            if not automation_token:
                return JSONResponse({"detail": "automation is not configured"}, status_code=503)
            offered = request.headers.get("x-shop-token", "")
            if not hmac.compare_digest(offered.encode(), automation_token.encode()):
                return JSONResponse({"detail": "automation credential required"}, status_code=401)
        elif path.startswith("/shop/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            expected_origin = origin_for(request)
            origin = request.headers.get("origin", "")
            cookie, token = request.cookies.get("shop_csrf", ""), request.headers.get("x-csrf-token", "")
            if not expected_origin or origin != expected_origin or not cookie or not token or not hmac.compare_digest(cookie.encode(), token.encode()):
                return JSONResponse({"detail": "same-origin CSRF token required"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Invalid)
    async def invalid_handler(request, exc):
        status = 404 if isinstance(exc, NotFound) else 409 if isinstance(exc, Conflict) else 422
        return JSONResponse({"detail": str(exc)}, status_code=status)

    @app.exception_handler(ReportError)
    async def report_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/healthz")
    def health():
        return {"ok": True}

    @app.get("/shop/api/session")
    def session(request: Request):
        existing = request.cookies.get("shop_csrf", "")
        token = existing if 32 <= len(existing) <= 128 and all(c.isalnum() or c in "-_" for c in existing) else secrets.token_urlsafe(32)
        response = JSONResponse({"csrf_token": token})
        response.set_cookie("shop_csrf", token, httponly=True, secure=(origin_for(request) or "").startswith("https://"), samesite="strict", path="/shop")
        return response

    @app.get("/shop/api/jobs")
    def jobs():
        posted = affiliate.posted_counts()
        return [{**job, "posts": posted.get(job["id"], 0)} for job in store.list_jobs()]

    @app.post("/shop/api/jobs", status_code=201)
    def create(body: Product):
        return store.create_job(body.model_dump())

    @app.get("/shop/api/jobs/{job_id}")
    def job(job_id: str):
        return {**store.get_job(job_id), "assets": store.list_assets(job_id), "renders": store.list_renders(job_id)}

    @app.patch("/shop/api/jobs/{job_id}")
    def edit(job_id: str, body: Edit):
        return store.update_job(job_id, body.revision, body.model_dump(exclude={"revision"}, exclude_unset=True))

    @app.post("/shop/api/jobs/{job_id}/plan/request", status_code=202)
    def request_plan(job_id: str, body: Revision):
        return store.request_plan(job_id, body.revision)

    @app.put("/shop/api/jobs/{job_id}/plan")
    def save_plan(job_id: str, body: PlanEdit):
        return store.save_plan(job_id, body.revision, body.plan)

    @app.post("/shop/api/jobs/{job_id}/plan/approve")
    def approve_plan(job_id: str, body: Revision):
        return store.approve_plan(job_id, body.revision)

    @app.post("/shop/api/jobs/{job_id}/references", status_code=201)
    def reference(job_id: str, revision: int = Form(...), file: UploadFile = File(...)):
        return store.add_asset(job_id, revision, "reference", file.filename or "", file.file)

    @app.delete("/shop/api/jobs/{job_id}/references/{asset_id}")
    def remove_reference(job_id: str, asset_id: str, body: Revision):
        return store.remove_reference(job_id, body.revision, asset_id)

    @app.post("/shop/api/jobs/{job_id}/scenes/{scene_id}/media", status_code=201)
    def media(job_id: str, scene_id: str, revision: int = Form(...), file: UploadFile = File(...)):
        return store.add_asset(job_id, revision, "scene", file.filename or "", file.file, scene_id=scene_id)

    @app.post("/shop/api/jobs/{job_id}/scenes/{scene_id}/accept")
    def accept(job_id: str, scene_id: str, body: Accept):
        return store.accept_scene(job_id, body.revision, scene_id, reference_matches=body.reference_matches)

    @app.get("/shop/api/jobs/{job_id}/assets/{asset_id}")
    def asset(job_id: str, asset_id: str):
        record = store.get_asset(asset_id, job_id)
        if record["validation"] != "valid":
            raise Conflict("asset has not passed validation")
        path = store.asset_path(asset_id, job_id)
        if not path.is_file():
            raise NotFound("asset file not found")
        return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                            filename=record["name"], content_disposition_type="inline")

    @app.get("/shop/api/jobs/{job_id}/plan/pack")
    def pack(job_id: str):
        record = store.get_job(job_id)
        if not record["plan_approved_at"]:
            raise Conflict("approve plan before downloading the reference pack")
        with tempfile.NamedTemporaryFile(prefix="shop-pack-", suffix=".zip", delete=False) as handle:
            path = Path(handle.name)
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("plan.json", json.dumps(record["plan"], ensure_ascii=False, indent=2))
                prompts = []
                for index, scene in enumerate(record["plan"]["scenes"], 1):
                    prompts.append(f"Scene {index}\n{scene.get('flow_prompt', '')}\n")
                archive.writestr("prompts.txt", "\n".join(prompts))
                for reference in record["references"]:
                    asset = store.get_asset(reference, job_id)
                    archive.write(store.asset_path(reference, job_id), "references/" + asset["key"])
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return FileResponse(path, filename="shop-reference-pack.zip", media_type="application/zip", background=BackgroundTask(path.unlink, missing_ok=True))

    @app.post("/shop/api/jobs/{job_id}/renders", status_code=202)
    def request_render(job_id: str, body: RenderRequest):
        return store.request_render(job_id, body.revision, retry=body.retry)

    @app.get("/shop/api/jobs/{job_id}/renders/{render_id}")
    def render(job_id: str, render_id: str):
        record = store.get_render(render_id)
        if record["job_id"] != job_id:
            raise NotFound("render not found")
        return record

    @app.post("/shop/api/jobs/{job_id}/renders/{render_id}/approve")
    def approve_render(job_id: str, render_id: str, body: Revision):
        return store.approve_render(job_id, body.revision, render_id)

    @app.get("/shop/api/jobs/{job_id}/renders/{render_id}/media/{kind}")
    def render_media(job_id: str, render_id: str, kind: str):
        record = store.get_render(render_id)
        if record["job_id"] != job_id or record["status"] != "ready" or kind not in ("video", "thumbnail", "caption"):
            raise NotFound("render asset not found")
        key = record["outputs"].get(kind)
        if not isinstance(key, str):
            raise NotFound("render asset not found")
        path = (store.media_root / key).resolve()
        if not path.is_relative_to(store.media_root.resolve()) or not path.is_file():
            raise NotFound("render asset not found")
        return FileResponse(path, filename=path.name)

    @app.get("/shop/api/jobs/{job_id}/affiliate")
    def affiliate_view(job_id: str):
        return affiliate.job_view(job_id)

    @app.put("/shop/api/jobs/{job_id}/affiliate")
    def affiliate_product(job_id: str, body: ProductInfo):
        return affiliate.update_product(job_id, body.revision, body.model_dump(exclude={"revision"}, exclude_unset=True))

    @app.post("/shop/api/jobs/{job_id}/posts", status_code=201)
    def add_post(job_id: str, body: Post):
        return affiliate.add_post(job_id, body.model_dump(exclude_unset=True))

    @app.patch("/shop/api/jobs/{job_id}/posts/{post_id}")
    def edit_post(job_id: str, post_id: str, body: PostEdit):
        return affiliate.update_post(job_id, post_id, body.model_dump(exclude_unset=True))

    @app.delete("/shop/api/jobs/{job_id}/posts/{post_id}", status_code=204)
    def delete_post(job_id: str, post_id: str):
        affiliate.delete_post(job_id, post_id)

    @app.post("/shop/api/affiliate/imports", status_code=201)
    def import_report(file: UploadFile = File(...)):
        data = file.file.read(REPORT_LIMIT + 1)
        if len(data) > REPORT_LIMIT:
            raise Invalid("report exceeds 20 MiB; export a shorter date range")
        if not data:
            raise Invalid("empty report")
        return affiliate.import_report(file.filename or "report.csv", data)

    @app.get("/shop/api/affiliate/summary")
    def revenue_summary():
        return affiliate.summary()

    @app.get("/shop/automation/pending")
    def pending():
        return store.pending_dispatches()

    @app.post("/shop/automation/renders/{render_id}/start")
    def start(render_id: str, body: Start):
        record = store.start_render(render_id, body.revision, body.idempotency_key)
        return {k: record[k] for k in ("id", "job_id", "revision", "status", "attempt", "error", "updated_at")}

    @app.get("/shop/automation/renders/{render_id}")
    def automation_render(render_id: str):
        record = store.get_render(render_id)
        return {k: record[k] for k in ("id", "job_id", "revision", "status", "attempt", "error", "updated_at")}

    @app.post("/shop/automation/notifications", status_code=202)
    def notify(body: Notification):
        return store.notify(body.job_id, body.milestone, body.idempotency_key, render_id=body.render_id, retry=body.retry)

    @app.post("/shop/api/jobs/{job_id}/notifications/retry")
    def retry_notifications(job_id: str, body: Revision):
        return store.retry_notifications(job_id, body.revision)

    from app.shop_views import register_views

    register_views(app, store)
    return app
