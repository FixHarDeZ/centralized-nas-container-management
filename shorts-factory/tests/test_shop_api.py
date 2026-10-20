import io

import pytest
from app.shop_api import create_app
from fastapi.testclient import TestClient

from .test_shop_store import prepared


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_AUTOMATION_TOKEN", "scoped-secret")
    monkeypatch.setenv("STUDIO_INBOX", str(tmp_path / "inbox"))
    return TestClient(create_app(tmp_path))


def browser(client):
    session = client.get("/shop/api/session").json()
    return {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}


def test_csrf_origin_and_crud(client):
    assert client.post("/shop/api/jobs", json={"name": "Cup"}).status_code == 403
    headers = browser(client)
    assert client.post("/shop/api/jobs", json={"name": "Cup"}, headers={**headers, "Origin": "https://evil.example"}).status_code == 403
    response = client.post("/shop/api/jobs", json={"name": "Cup"}, headers=headers)
    assert response.status_code == 201
    job = response.json()
    assert client.get("/shop/api/jobs").json()[0]["id"] == job["id"]
    assert client.get(f"/shop/api/jobs/{job['id']}").json()["assets"] == []
    response = client.patch(f"/shop/api/jobs/{job['id']}", json={"revision": 1, "brief": "Blue"}, headers=headers)
    assert response.json()["revision"] == 2
    assert client.patch(f"/shop/api/jobs/{job['id']}", json={"revision": 1, "brief": "old"}, headers=headers).status_code == 409


def test_proxy_https_session_cookie(client):
    response = client.get("/shop/api/session", headers={"X-Forwarded-Proto": "https"})
    assert "Secure" in response.headers["set-cookie"]
    token = response.json()["csrf_token"]
    response = client.post("/shop/api/jobs", json={"name": "Cup"}, headers={"Origin": "https://testserver", "X-Forwarded-Proto": "https", "X-CSRF-Token": token, "Cookie": f"shop_csrf={token}"})
    assert response.status_code == 201


def test_upload_ownership_media_and_approval_gate(client):
    headers = browser(client)
    job = client.post("/shop/api/jobs", json={"name": "Cup"}, headers=headers).json()
    response = client.post(f"/shop/api/jobs/{job['id']}/references", data={"revision": 1}, files={"file": ("../../cup.jpg", io.BytesIO(b"jpeg"), "image/jpeg")}, headers=headers)
    assert response.status_code == 201
    asset = response.json()
    path = f"/shop/api/jobs/{job['id']}/assets/{asset['id']}"
    assert client.get(path).status_code == 409
    client.app.state.store.validate_asset(asset["id"], {"width": 10, "height": 10}, valid=True)
    assert client.get(path).content == b"jpeg"
    other = client.post("/shop/api/jobs", json={"name": "Other"}, headers=headers).json()
    assert client.get(f"/shop/api/jobs/{other['id']}/assets/{asset['id']}").status_code == 404


def test_automation_is_scoped_and_idempotent(client):
    job = prepared(client.app.state.store)
    headers = browser(client)
    render = client.post(f"/shop/api/jobs/{job['id']}/renders", json={"revision": job["revision"]}, headers=headers).json()
    assert client.get("/shop/automation/pending").status_code == 401
    assert client.get("/shop/automation/pending", headers={"X-Shop-Token": "wrong"}).status_code == 401
    automation = {"X-Shop-Token": "scoped-secret"}
    assert client.get("/shop/automation/pending", headers=automation).json()[0]["id"] == render["id"]
    start = f"/shop/automation/renders/{render['id']}/start"
    body = {"revision": job["revision"], "idempotency_key": "reconcile-1"}
    assert client.post(start, json={**body, "revision": 1}, headers=automation).status_code == 409
    assert client.post(start, json=body, headers=automation).json()["status"] == "queued"
    assert client.post(start, json=body, headers=automation).json()["status"] == "queued"
    assert client.post("/shop/api/jobs", json={"name": "No csrf"}, headers=automation).status_code == 403


def test_unconfigured_automation_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("SHOP_AUTOMATION_TOKEN", raising=False)
    client = TestClient(create_app(tmp_path))
    assert client.get("/shop/automation/pending", headers={"X-Shop-Token": ""}).status_code == 503


def test_plan_pack_render_files_and_outdated_approval(client, tmp_path):
    headers = browser(client)
    store = client.app.state.store
    job = prepared(store)
    assert client.get(f"/shop/api/jobs/{job['id']}/plan/pack").headers["content-type"] == "application/zip"
    render = store.request_render(job["id"], job["revision"])
    store.start_render(render["id"], job["revision"], "start")
    output = store.media_root / "renders" / "final.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"complete video")
    store.set_render_result(render["id"], "ready", outputs={"video": "renders/final.mp4", "caption": "../../outside.txt"})
    path = f"/shop/api/jobs/{job['id']}/renders/{render['id']}"
    assert client.get(path + "/media/video").content == b"complete video"
    assert client.get(path + "/media/caption").status_code == 404
    edited = store.update_job(job["id"], job["revision"], {"brief": "Changed"})
    assert client.post(path + "/approve", json={"revision": edited["revision"]}, headers=headers).status_code == 409
    assert client.get("/shop/automation/renders/" + render["id"], headers={"X-Shop-Token": "scoped-secret"}).json()["status"] == "ready"


def test_plan_routes_reject_unvalidated_and_stale_approval(client):
    from .test_shop_store import plan
    headers = browser(client)
    job = client.post("/shop/api/jobs", json={"name": "Cup"}, headers=headers).json()
    base = f"/shop/api/jobs/{job['id']}"
    job = client.put(base + "/plan", json={"revision": job["revision"], "plan": plan()}, headers=headers).json()
    assert client.post(base + "/plan/approve", json={"revision": job["revision"]}, headers=headers).status_code == 422
    assert client.post(base + "/plan/approve", json={"revision": 1}, headers=headers).status_code == 409
    assert client.post(base + "/renders", json={"revision": job["revision"]}, headers=headers).status_code == 422


def test_automation_start_only_returns_operational_fields(client):
    store = client.app.state.store
    job = prepared(store)
    render = store.request_render(job["id"], job["revision"])
    response = client.post(f"/shop/automation/renders/{render['id']}/start", json={"revision": job["revision"], "idempotency_key": "start"}, headers={"X-Shop-Token": "scoped-secret"})
    assert response.status_code == 200
    assert set(response.json()) == {"id", "job_id", "revision", "status", "attempt", "error", "updated_at"}


def test_csrf_session_is_stable_across_browser_tabs(tmp_path):
    client = TestClient(create_app(tmp_path))
    first = client.get('/shop/api/session').json()['csrf_token']
    second = client.get('/shop/api/session').json()['csrf_token']
    assert first == second
    response = client.post('/shop/api/jobs', json={'name': 'two tabs'},
                           headers={'Origin': 'http://testserver', 'X-CSRF-Token': first})
    assert response.status_code == 201


MP4_HEAD = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 100


def test_studio_inbox_accepts_an_mp4_for_a_token(client, tmp_path, monkeypatch):
    headers = browser(client)
    token = "a1b2c3d4e5f6"
    reply = client.post(f"/shop/api/studio-inbox/{token}", headers=headers,
                        files={"file": ("x.mp4", io.BytesIO(MP4_HEAD), "video/mp4")})
    assert reply.status_code == 201
    inbox = tmp_path / "inbox"
    assert (inbox / f"{token}.mp4").read_bytes() == MP4_HEAD
    assert not list(inbox.glob("*.part"))


def test_studio_inbox_refuses_bad_token_bad_media_and_no_csrf(client, tmp_path):
    headers = browser(client)
    files = {"file": ("x.mp4", io.BytesIO(MP4_HEAD), "video/mp4")}
    # The client folds `../..` into /shop/etc, a GET-only view route (405):
    # the traversal never reaches the inbox route at all.
    assert client.post("/shop/api/studio-inbox/../../etc", headers=headers, files=files).status_code in (404, 405, 422)
    assert client.post("/shop/api/studio-inbox/ZZZZZZZZZZZZ", headers=headers, files=files).status_code == 422
    assert client.post("/shop/api/studio-inbox/a1b2c3d4e5f6", headers=headers,
                       files={"file": ("x.mp4", io.BytesIO(b"not a video at all"), "video/mp4")}).status_code == 422
    assert client.post("/shop/api/studio-inbox/a1b2c3d4e5f6",
                       files={"file": ("x.mp4", io.BytesIO(MP4_HEAD), "video/mp4")}).status_code == 403
    assert not (tmp_path / "inbox" / "a1b2c3d4e5f6.mp4").exists()


def test_studio_inbox_refuses_a_file_over_the_cap(client, tmp_path, monkeypatch):
    import app.shop_api as shop_api

    monkeypatch.setattr(shop_api, "STUDIO_LIMIT", 64)
    reply = client.post("/shop/api/studio-inbox/a1b2c3d4e5f6", headers=browser(client),
                        files={"file": ("x.mp4", io.BytesIO(MP4_HEAD), "video/mp4")})
    assert reply.status_code == 422
    inbox = tmp_path / "inbox"
    assert not (inbox / "a1b2c3d4e5f6.mp4").exists()
    assert not list(inbox.glob("*.part"))


def test_studio_job_routes_need_csrf_and_a_studio_plan(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    headers = browser(client)
    job = client.post("/shop/api/jobs", json={"name": "Lamp", "mode": "studio", "character": "auto"},
                      headers=headers).json()
    assert job["mode"] == "studio" and job["character"] == "auto"
    files = {"file": ("flow.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")}
    assert client.post(f"/shop/api/jobs/{job['id']}/export", data={"revision": job["revision"]},
                       files=files).status_code == 403
    refused = client.post(f"/shop/api/jobs/{job['id']}/export", data={"revision": job["revision"]},
                          files=files, headers=headers)
    assert refused.status_code == 422 and "approve the Studio plan" in refused.json()["detail"]
    even = client.post(f"/shop/api/jobs/{job['id']}/export/even", json={"revision": job["revision"]},
                       headers=headers)
    assert even.status_code == 422
    page = client.get(f"/shop/{job['id']}").text
    assert 'value="studio" selected' in page and "🤖 ให้บอทแต่ง" in page
