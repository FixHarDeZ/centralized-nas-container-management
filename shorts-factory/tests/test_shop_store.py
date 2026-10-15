import io

import pytest
from app.shop_store import Conflict, Invalid, NotFound, Store


def plan(reference=None):
    return {"title": "Cup", "caption": "Facts #ad", "scenes": [
        {"id": str(i), "source": "flow" if i == 0 else "still", "narration": "cup",
         "lines": ["Cup"], "flow_prompt": "Show cup without text", "reference_id": reference,
         "fit": "contain", "required_duration": 8} for i in range(3)]}


def prepared(store):
    job = store.create_job({"name": "Cup", "brief": "A ceramic cup", "destination": "facebook"})
    ref = store.add_asset(job["id"], job["revision"], "reference", "cup.jpg", io.BytesIO(b"jpeg"))
    store.validate_asset(ref["id"], {"width": 400, "height": 600}, valid=True)
    job = store.get_job(job["id"])
    job = store.save_plan(job["id"], job["revision"], plan(ref["id"]))
    store.validate_plan(job["id"], job["plan_version"], valid=True)
    job = store.approve_plan(job["id"], job["revision"])
    video = store.add_asset(job["id"], job["revision"], "scene", "clip.mp4", io.BytesIO(b"video"), scene_id="0")
    store.validate_asset(video["id"], {"duration": 10, "width": 1080, "height": 1920}, valid=True)
    job = store.get_job(job["id"])
    for scene in job["plan"]["scenes"]:
        job = store.accept_scene(job["id"], job["revision"], scene["id"], reference_matches=True)
    return job


def test_restart_stale_edits_and_validation_gate(tmp_path):
    store = Store(tmp_path)
    job = store.create_job({"name": "Cup", "brief": "Ceramic"})
    assert Store(tmp_path).get_job(job["id"])["name"] == "Cup"
    ref = store.add_asset(job["id"], job["revision"], "reference", "cup.jpg", io.BytesIO(b"jpeg"))
    store.validate_asset(ref["id"], {}, valid=True)
    job = store.get_job(job["id"])
    edited = store.update_job(job["id"], job["revision"], {"brief": "Blue ceramic"})
    with pytest.raises(Conflict):
        store.update_job(job["id"], job["revision"], {"name": "stale"})
    job = store.save_plan(job["id"], edited["revision"], plan(ref["id"]))
    with pytest.raises(Invalid, match="validat"):
        store.approve_plan(job["id"], job["revision"])
    store.validate_plan(job["id"], job["plan_version"], valid=True)
    approved = store.approve_plan(job["id"], job["revision"])
    edited = store.save_plan(job["id"], approved["revision"], plan())
    assert edited["plan_approved_at"] is None
    with pytest.raises(Conflict):
        store.validate_plan(job["id"], job["plan_version"], valid=True)


def test_immutable_render_dispatch_retry_and_lease_recovery(tmp_path):
    store = Store(tmp_path)
    job = prepared(store)
    render = store.request_render(job["id"], job["revision"])
    assert render["status"] == "pending_dispatch"
    assert store.request_render(job["id"], job["revision"])["id"] == render["id"]
    assert store.pending_dispatches()[0]["id"] == render["id"]
    assert store.start_render(render["id"], job["revision"], "n8n-key")["status"] == "queued"
    assert store.start_render(render["id"], job["revision"], "n8n-key")["id"] == render["id"]
    command = store.claim_command("worker", kinds=["render"], lease_seconds=1, now=100)
    assert command["payload"]["render_id"] == render["id"]
    assert store.claim_command("worker2", kinds=["render"], now=100) is None
    recovered = store.claim_command("worker2", kinds=["render"], now=102)
    assert recovered["id"] == command["id"]
    with pytest.raises(Conflict):
        store.finish_command(command["id"], "worker")
    store.set_render_result(render["id"], "failed", error="short clip")
    retry = store.request_render(job["id"], job["revision"], retry=True)
    assert retry["id"] != render["id"] and retry["attempt"] == 2
    edited = store.update_job(job["id"], job["revision"], {"brief": "new facts"})
    assert edited["revision"] > job["revision"]
    assert store.get_render(render["id"])["snapshot"]["brief"] == "A ceramic cup"


def test_upload_ownership_generated_paths_and_acceptance(tmp_path):
    store = Store(tmp_path)
    job = store.create_job({"name": "Cup"})
    with pytest.raises(Invalid):
        store.add_asset(job["id"], job["revision"], "reference", "../../bad.exe", io.BytesIO(b"x"))
    asset = store.add_asset(job["id"], job["revision"], "reference", "../../cup.jpg", io.BytesIO(b"x"))
    assert asset["name"] == "cup.jpg"
    assert store.asset_path(asset["id"], job["id"]).parent == tmp_path / "assets"
    other = store.create_job({"name": "Other"})
    with pytest.raises(NotFound):
        store.asset_path(asset["id"], other["id"])
    with pytest.raises(Invalid):
        store.add_asset(job["id"], 2, "reference", "empty.jpg", io.BytesIO(b""))


def test_invalid_and_missing_media_block_render_and_preserve_previous(tmp_path):
    store = Store(tmp_path)
    job = prepared(store)
    prior = job["plan"]["scenes"][0]["media_id"]
    replacement = store.add_asset(job["id"], job["revision"], "scene", "bad.mp4", io.BytesIO(b"bad"), scene_id="0")
    store.validate_asset(replacement["id"], {}, valid=False, error="not video")
    current = store.get_job(job["id"])
    assert current["plan"]["scenes"][0]["media_id"] == prior
    assert current["plan"]["scenes"][0]["accepted_at"]
    assert store.request_render(current["id"], current["revision"])


def test_notification_idempotency_and_command_retry(tmp_path):
    store = Store(tmp_path)
    job = store.create_job({"name": "Cup"})
    first = store.notify(job["id"], "waiting", "milestone-1")
    assert store.notify(job["id"], "waiting", "milestone-1")["id"] == first["id"]
    command = store.claim_command("worker", kinds=["notify"])
    store.finish_command(command["id"], "worker", error="telegram offline")
    assert store.claim_command("worker", kinds=["notify"])["id"] == command["id"]


def test_plan_edit_retains_media_but_invalidates_acceptance(tmp_path):
    store = Store(tmp_path)
    job = prepared(store)
    media = job["plan"]["scenes"][0]["media_id"]
    updated = store.save_plan(job["id"], job["revision"], job["plan"])
    assert updated["plan"]["scenes"][0]["media_id"] == media
    assert all(s["accepted_at"] is None for s in updated["plan"]["scenes"])
    assert updated["plan_approved_at"] is None


def test_reference_removal_preserves_immutable_asset(tmp_path):
    store = Store(tmp_path)
    job = prepared(store)
    reference = job["references"][0]
    edited = store.remove_reference(job["id"], job["revision"], reference)
    assert edited["references"] == []
    assert edited["plan"]["scenes"][1]["reference_id"] is None
    assert store.asset_path(reference).is_file()
    with pytest.raises(Invalid):
        store.request_render(job["id"], edited["revision"])


def test_final_approval_does_not_make_its_own_render_outdated(tmp_path):
    store = Store(tmp_path)
    job = prepared(store)
    render = store.request_render(job["id"], job["revision"])
    store.start_render(render["id"], job["revision"], "start")
    store.set_render_result(render["id"], "ready", outputs={"video": "renders/final.mp4"})
    approved = store.approve_render(job["id"], job["revision"], render["id"])
    assert approved["revision"] == render["revision"]
    assert approved["final_approved_render_id"] == render["id"]


def test_simultaneous_edit_has_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    store = Store(tmp_path)
    job = store.create_job({"name": "Cup"})
    def edit(name):
        try:
            return store.update_job(job["id"], 1, {"name": name})["name"]
        except Conflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ["A", "B"]))
    assert results.count("conflict") == 1


def test_upload_bounds_and_snapshot_ownership(tmp_path):
    store = Store(tmp_path)
    job = store.create_job({"name": "Cup"})
    class TooLarge:
        def __init__(self):
            self.calls = 0
        def read(self, size):
            self.calls += 1
            return b"x" * (1024 * 1024) if self.calls <= 16 else b""
    with pytest.raises(Invalid, match="limit"):
        store.add_asset(job["id"], 1, "reference", "too-big.jpg", TooLarge())
    assert not list(store.assets_dir.iterdir())
    job = prepared(store)
    other = store.create_job({"name": "Other"})
    foreign_plan = plan(job["references"][0])
    with pytest.raises(Invalid, match="belong"):
        store.save_plan(other["id"], 1, foreign_plan)
    with pytest.raises(Invalid, match="confirm"):
        store.accept_scene(job["id"], job["revision"], "0", reference_matches=False)


def test_late_probe_cannot_replace_newer_scene_upload(tmp_path):
    store = Store(tmp_path)
    job = prepared(store)
    first = store.add_asset(job["id"], job["revision"], "scene", "first.mp4", io.BytesIO(b"first"), scene_id="0")
    job = store.get_job(job["id"])
    second = store.add_asset(job["id"], job["revision"], "scene", "second.mp4", io.BytesIO(b"second"), scene_id="0")
    store.validate_asset(second["id"], {"duration": 10}, valid=True)
    store.validate_asset(first["id"], {"duration": 10}, valid=True)
    assert store.get_job(job["id"])["plan"]["scenes"][0]["media_id"] == second["id"]


def test_expired_lease_cannot_publish_result(tmp_path):
    store = Store(tmp_path)
    job = prepared(store)
    render = store.request_render(job["id"], job["revision"])
    store.start_render(render["id"], job["revision"], "start")
    command = store.claim_command("stale-worker", kinds=["render"], now=1, lease_seconds=1)
    with pytest.raises(Conflict, match="lease"):
        store.set_render_result(render["id"], "ready", command_id=command["id"], owner="stale-worker")
    assert store.get_render(render["id"])["status"] == "queued"


@pytest.mark.parametrize("duration", ["bad", None, -1, 61, float("nan")])
def test_scene_duration_must_be_bounded_number(tmp_path, duration):
    store = Store(tmp_path)
    job = store.create_job({"name": "Cup"})
    proposed = plan()
    proposed["scenes"][0]["required_duration"] = duration
    with pytest.raises(Invalid, match="duration"):
        store.save_plan(job["id"], 1, proposed)


def test_plan_approval_requires_reference_and_selected_scene_reference(tmp_path):
    store = Store(tmp_path)
    job = store.create_job({"name": "Cup"})
    job = store.save_plan(job["id"], 1, plan())
    store.validate_plan(job["id"], job["plan_version"], valid=True)
    with pytest.raises(Invalid, match="reference"):
        store.approve_plan(job["id"], job["revision"])


def test_lost_monitor_rediscovers_terminal_render_until_notification_delivery(tmp_path):
    store = Store(tmp_path)
    job = prepared(store)
    render = store.request_render(job["id"], job["revision"])
    store.start_render(render["id"], job["revision"], "start")
    store.set_render_result(render["id"], "ready", outputs={"video": "renders/final.mp4"})
    # A fresh reconciliation discovers a completion even if its prior poll died.
    assert Store(tmp_path).pending_dispatches()[0]["status"] == "ready"
    first = store.notify(job["id"], "ready", "random-key-a", render_id=render["id"])
    duplicate = store.notify(job["id"], "ready", "random-key-b", render_id=render["id"])
    assert first["id"] == duplicate["id"]
    assert store.pending_dispatches() == []
    command = store.claim_command("worker", kinds=["notify"])
    store.finish_command(command["id"], "worker")
    assert Store(tmp_path).pending_dispatches() == []
    assert store.notify(job["id"], "ready", "random-key-c", render_id=render["id"])["status"] == "done"


def test_exhausted_notification_is_visible_and_explicitly_retryable(tmp_path):
    store = Store(tmp_path)
    job = prepared(store)
    render = store.request_render(job["id"], job["revision"])
    store.start_render(render["id"], job["revision"], "start")
    store.set_render_result(render["id"], "failed", error="render failed")
    store.notify(job["id"], "failed", "one", render_id=render["id"])
    command = store.claim_command("worker", kinds=["notify"])
    store.finish_command(command["id"], "worker", error="Telegram unavailable", retry=False)
    assert store.pending_dispatches()[0]["notification_error"] == "Telegram unavailable"
    assert store.get_job(job["id"])["notification_error"] == "Telegram unavailable"
    assert store.notify(job["id"], "failed", "new-random-key", render_id=render["id"])["status"] == "failed"
    assert store.claim_command("worker", kinds=["notify"]) is None
    retried = store.notify(job["id"], "failed", "explicit", render_id=render["id"], retry=True)
    assert retried["id"] == command["id"] and retried["status"] == "queued"
    command = store.claim_command("worker", kinds=["notify"])
    store.finish_command(command["id"], "worker")
    assert store.get_job(job["id"])["notification_error"] is None
    assert store.pending_dispatches() == []


def test_generation_failure_preserves_previously_validated_plan(tmp_path):
    store = Store(tmp_path)
    job = prepared(store)
    prior = job["plan"]
    command = store.request_plan(job["id"], job["revision"])
    command = store.claim_command("worker", kinds=["generate_plan"])
    store.finish_command(command["id"], "worker", error="model unavailable", retry=False)
    failed = store.get_job(job["id"])
    assert failed["generation_error"] == "model unavailable"
    assert failed["plan_error"] is None
    assert failed["validated_plan_version"] == job["plan_version"]
    assert failed["plan_approved_at"] == job["plan_approved_at"]
    assert failed["plan"] == prior


def test_notification_retry_cycle_has_store_enforced_attempt_ceiling(tmp_path):
    store = Store(tmp_path)
    job = store.create_job({"name": "Cup"})
    command = store.notify(job["id"], "waiting", "event")
    for attempt in range(3):
        command = store.claim_command("worker", kinds=["notify"])
        assert command["attempts"] == attempt + 1
        store.finish_command(command["id"], "worker", error="offline")
    assert store.claim_command("worker", kinds=["notify"]) is None
    assert store.notify(job["id"], "waiting", "another-key")["status"] == "failed"


def test_worker_plan_mutation_rejects_expired_command_owner(tmp_path):
    store = Store(tmp_path)
    job = prepared(store)
    command = store.request_plan(job['id'], job['revision'])
    claimed = store.claim_command('old-worker', kinds=['generate_plan'], now=1, lease_seconds=1)
    assert claimed['id'] == command['id']
    with pytest.raises(Conflict):
        store.save_plan(job['id'], job['revision'], job['plan'],
                        command_id=command['id'], owner='old-worker')
    assert store.get_job(job['id'])['revision'] == job['revision']


def test_failed_generation_can_be_retried_without_editing_product(tmp_path):
    store = Store(tmp_path)
    job = prepared(store)
    request = store.request_plan(job['id'], job['revision'])
    command = store.claim_command('worker', kinds=['generate_plan'])
    store.finish_command(command['id'], 'worker', error='provider unavailable', retry=False)
    retried = store.request_plan(job['id'], job['revision'])
    assert retried['id'] == request['id']
    assert retried['status'] == 'queued'
    assert store.get_job(job['id'])['generation_status'] == 'queued'
