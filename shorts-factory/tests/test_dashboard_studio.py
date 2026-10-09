"""Creator Studio regressions: audience isolation and preserved user edits."""
import json

import pytest

from . import test_dashboard

client = test_dashboard.client
config_dir = test_dashboard.config_dir
data_dir = test_dashboard.data_dir


def test_channel_summary_keeps_audiences_separate(client, data_dir):
    from app import dashboard, history
    history.PATH.write_text(json.dumps([
        {"video_id": "thai"}, {"video_id": "english", "locale": "en"},
    ]), encoding="utf-8")
    rows = [dashboard._row({"snapshots": [{"age_days": 7, "views": 10, "percent": 40}]}),
            dashboard._row({"locale": "en", "snapshots": [{"age_days": 7, "views": 900, "percent": 90}]})]
    thai = dashboard._summary(rows, "th")
    english = dashboard._summary(rows, "en")
    assert thai["published"] == english["published"] == 1
    assert thai["views"] == 10 and thai["median"] == 40
    assert english["views"] == 900 and english["median"] == 90
    assert thai["total"] == english["total"] == 1


def test_library_channel_gate_counts_the_matching_history(client, data_dir):
    from app import history
    entries = [{"video_id": f"en{n}", "locale": "en"} for n in range(30)]
    entries.append({"video_id": "thai"})
    history.PATH.write_text(json.dumps(entries), encoding="utf-8")
    channels = {channel["code"]: channel for channel in client.get("/").context["channels"]}
    assert channels["th"]["summary"]["published"] == 1
    assert "1/30" in channels["th"]["gate"]
    assert channels["en"]["summary"]["published"] == 30
    assert channels["en"]["gate"] is None


def test_unmeasured_summary_is_not_a_zero_view_result(client):
    from app import dashboard
    summary = dashboard._summary([dashboard._row({})], "th")
    assert summary["views"] is None
    assert summary["median"] is None
    assert summary["measured"] == 0
    measured = dashboard._summary([dashboard._row({
        "snapshots": [{"age_days": 7, "views": 0, "percent": 0}],
    })], "th")
    assert measured["views"] == measured["median"] == 0
    assert measured["measured"] == 1


def test_library_rows_have_legacy_locale_and_searchable_title(client):
    from app import dashboard
    row = dashboard._row({"id": "old-1", "topic": "หัวข้อ", "scripts": [
        {"script": {"title": "ชื่อสำหรับค้นหา", "category": "devops"}},
    ]})
    assert row["locale_code"] == "th"
    assert "ชื่อสำหรับค้นหา" in row["search"] and "old-1" in row["search"]
    assert "devops" in row["search"]


def test_status_does_not_present_an_old_draft_as_active_review(client):
    from app import dashboard
    state = {"mode": "review", "clip_id": "new"}
    old = dashboard._row({"id": "old", "outcome": "drafting"}, state)
    current = dashboard._row({"id": "new", "outcome": "drafting"}, state)
    assert "รีวิว" not in old["status"]["label"]
    assert "รีวิว" in current["status"]["label"]


def test_unknown_outcome_remains_visible_and_filterable(client, data_dir):
    path = data_dir / "clips" / "20260802-120000-000.json"
    record = json.loads(path.read_text())
    record["outcome"] = "future_outcome"
    path.write_text(json.dumps(record), encoding="utf-8")
    reply = client.get("/")
    row = next(row for row in reply.context["rows"] if row["id"] == record["id"])
    assert row["status"]["label"] == "future_outcome"
    assert row["status"]["key"] == "future_outcome"
    assert "future_outcome" in reply.text


def test_failure_filter_labels_both_kinds_of_failure(client, data_dir):
    for n, outcome in enumerate(["generate_failed", "render_failed"]):
        clip_id = f"20260803-failed-{n}"
        (data_dir / "clips" / f"{clip_id}.json").write_text(json.dumps({
            "id": clip_id, "created_at": "2026-08-03", "outcome": outcome,
        }), encoding="utf-8")
    reply = client.get("/")
    failed = [status for status in reply.context["statuses"] if status["key"] == "failed"]
    assert len(failed) == 1 and failed[0]["label"] == "ล้มเหลว"
    assert "เขียนไม่สำเร็จ" in reply.text and "เรนเดอร์ไม่สำเร็จ" in reply.text


def test_clip_context_has_latest_script_and_text_pronunciation_checks(client, data_dir):
    path = data_dir / "clips" / "20260801-120000-000.json"
    record = json.loads(path.read_text())
    record["scripts"].append({"at": "2026-08-01T12:04:00", "script": {
        "title": "CPU เร็วขึ้น", "cards": [{"narration": "CPU เร็วขึ้น", "spoken": "ซีพียูเร็วขึ้น"}],
    }})
    path.write_text(json.dumps(record), encoding="utf-8")
    reply = client.get("/clip/20260801-120000-000")
    assert reply.context["latest"]["script"]["title"] == "CPU เร็วขึ้น"
    assert len(reply.context["previous_drafts"]) == 1
    assert reply.context["checks"][0]["term"] == "CPU"
    assert reply.context["checks"][0]["cards"] == [1]
    assert "RAM หายไปไหน" in reply.text and "CPU เร็วขึ้น" in reply.text


def test_rejected_settings_keep_the_entire_edit(client, config_dir):
    reply = client.post("/settings", data={
        "th_enabled": "on", "th_hours": "8,99", "th_minutes": "17",
        "en_enabled": "on", "en_hours": "21", "en_minutes": "31",
        "model_primary": "mimo-v2.5", "model_fallback": "mimo-v2.5-pro",
    })
    assert reply.status_code == 400
    rows = {row["code"]: row for row in reply.context["rows"]}
    assert rows["th"]["hours"] == "8,99" and rows["th"]["minutes"] == "17"
    assert rows["en"]["enabled"] is True and rows["en"]["hours"] == "21"
    assert reply.context["models"]["primary"] == "mimo-v2.5"
    assert 'value="8,99"' in reply.text and 'value="17"' in reply.text
    assert not (config_dir / "schedule.json").exists()
    assert not (config_dir / "models.json").exists()


def test_rejected_unknown_model_is_visible_and_escaped(client, config_dir):
    bad_model = '<script>alert("x")</script>'
    reply = client.post("/settings", data={
        "th_enabled": "on", "th_hours": "8", "th_minutes": "15",
        "en_hours": "20", "en_minutes": "15", "model_primary": bad_model,
    })
    assert reply.status_code == 400
    assert reply.context["models"]["primary"] == bad_model
    assert '&lt;script&gt;' in reply.text
    assert '<script>alert("x")</script>' not in reply.text
    assert not (config_dir / "models.json").exists()


def test_now_labels_recorded_state_without_claiming_live_health(client):
    body = client.get("/now").text
    assert "สถานะที่บันทึกไว้" in body
    assert "heartbeat" in body


def test_view_formatting_preserves_unavailable_and_invalid_dates(client):
    from app import dashboard_view as view
    assert view.format_number(None) == "—"
    assert view.format_number(0) == "0"
    assert view.format_number(1234) == "1,234"
    assert view.format_date(None) == "—"
    assert view.format_date("not-a-date") == "not-a-date"
    assert view.format_date("2026-10-09T03:00:00Z") == "09/10/2026 · 10:00"


@pytest.mark.parametrize("filename", ["state.json", "say.json"])
def test_recorded_state_survives_a_non_object_file(client, data_dir, filename):
    (data_dir / filename).write_text("[]", encoding="utf-8")
    assert client.get("/now").status_code == 200


def test_clip_research_excludes_unsafe_source_links(client, data_dir):
    path = data_dir / "clips" / "20260801-120000-000.json"
    record = json.loads(path.read_text())
    record["research"] = {"results": [
        {"title": "unsafe", "url": "javascript:alert(1)"},
        {"title": "reference", "url": "https://example.com/source"},
    ]}
    path.write_text(json.dumps(record), encoding="utf-8")
    reply = client.get("/clip/20260801-120000-000")
    assert reply.context["sources"] == [{"title": "reference", "url": "https://example.com/source"}]


def test_experiment_does_not_name_a_winner_before_the_channel_gate(client, data_dir):
    for variant, percent in [("shock_number", 80), ("question", 40)]:
        for n in range(10):
            clip_id = f"20260803-{variant}-{n}"
            (data_dir / "clips" / f"{clip_id}.json").write_text(json.dumps({
                "id": clip_id, "locale": "th", "variant": variant,
                "outcome": "rendered", "created_at": "2026-08-03",
                "snapshots": [{"age_days": 7, "views": 100, "percent": percent}],
            }), encoding="utf-8")
    reply = client.get("/experiment")
    thai = next(section for section in reply.context["sections"] if section["locale"] == "th")
    assert thai["gate"]
    assert "สรุปไม่ได้" in thai["verdict"]
    assert "🏆" not in reply.text
