import asyncio
import io
from datetime import date

import pytest
from app.shop_affiliate import Affiliate, sub_id
from app.shop_report import ReportError, parse
from app.shop_store import Conflict, Invalid, Store

from .test_shop_store import prepared

CONVERSIONS = (
    "﻿Order id,Order Status,Item id,Item Name,Purchase Time,Item Total Commission,Sub_id1,Sub_id2,Sub_id3,Sub_id4,Sub_id5\n"
    "O1,Pending,I1,Cup,2026-10-01 10:00:00,\"฿1,234.50\",{fb},,,,\n"
    "O2,Completed,I1,Cup,2026-10-02 11:00:00,20,,x-{yt},,,\n"
    "O3,Cancelled,I1,Cup,2026-10-03 12:00:00,5,{fb},,,,\n"
    "O4,Completed,I9,Other,2026-10-04 12:00:00,7,,,,,\n"
)
CLICKS = "Click id,Click Time,Sub_id1\nC1,2026-10-01 09:00:00,{fb}\nC2,2026-10-20 09:00:00,{fb}\nC3,2026-10-20 09:00:00,other\n"


def ready_render(store, job):
    render = store.request_render(job["id"], job["revision"])
    store.start_render(render["id"], render["revision"], "k1")
    store.set_render_result(render["id"], "running")
    return render


def test_affiliate_writes_never_touch_job_revision_or_approvals(tmp_path):
    store = Store(tmp_path)
    affiliate = Affiliate(store)
    job = prepared(store)
    render = ready_render(store, job)
    before = store.get_job(job["id"])
    affiliate.update_product(job["id"], 0, {"product_url": "https://shopee.co.th/product/11/22", "commission_rate": "8"})
    post = affiliate.add_post(job["id"], {"channel": "facebook", "url": "https://fb.example/p", "posted_on": "2026-10-01"})
    affiliate.update_post(job["id"], post["id"], {"manual": {"clicks": "3"}})
    affiliate.import_report("c.csv", CONVERSIONS.format(fb="x", yt="y").encode())
    affiliate.job_view(job["id"])
    after = store.get_job(job["id"])
    for key in ("revision", "plan_version", "plan_approved_at", "final_approved_render_id", "status"):
        assert after[key] == before[key]
    assert [s["accepted_at"] for s in after["plan"]["scenes"]] == [s["accepted_at"] for s in before["plan"]["scenes"]]
    # A render that was running before the writes still lands on the job.
    store.set_render_result(render["id"], "ready", outputs={})
    assert store.get_job(job["id"])["status"] == "ready"
    store.approve_render(job["id"], after["revision"], render["id"])


def test_sub_ids_are_alphanumeric_stable_and_per_channel(tmp_path):
    store = Store(tmp_path)
    affiliate = Affiliate(store)
    job = store.create_job({"name": "Cup"})
    first = affiliate.job_view(job["id"])["channels"]
    assert {c: v["sub_id"] for c, v in first.items()} == {c: sub_id(job["id"], c) for c in ("shopee", "facebook", "youtube")}
    assert all(v["sub_id"].isalnum() and v["sub_id"].islower() for v in first.values())
    assert len({v["sub_id"] for v in first.values()}) == 3
    assert Affiliate(Store(tmp_path)).job_view(job["id"])["channels"] == first


def test_parse_conversions_handles_bom_baht_and_all_sub_id_slots():
    report = parse(CONVERSIONS.format(fb="AbC", yt="z").encode())
    assert report["kind"] == "conversions" and report["commission_level"] == "item"
    assert report["date_from"] == "2026-10-01" and report["date_to"] == "2026-10-04"
    first, second, third, _ = report["rows"]
    assert first["commission"] == 1234.5 and first["state"] == "pending" and first["sub_ids"] == ["abc"]
    assert second["state"] == "completed" and second["sub_ids"] == ["x", "z"]
    assert third["state"] == "cancelled"


def test_order_level_commission_counted_once_per_order():
    data = "Order id,Order Status,Item id,Total Commission,Sub_id1\nO1,Pending,A,10,s\nO1,Pending,B,10,s\nO2,Pending,A,4,s\n"
    rows = parse(data.encode())["rows"]
    assert [r["commission"] for r in rows] == [10, 0, 4]
    assert parse(data.encode())["commission_level"] == "order"


def test_thai_headers_buddhist_year_and_cp874():
    data = "รหัสคำสั่งซื้อ,สถานะคำสั่งซื้อ,รหัสสินค้า,ค่าคอมมิชชั่นรวม,เวลาสั่งซื้อ,Sub_id1\nO1,สำเร็จ,9,12,15/10/2569 10:00,abc\n"
    report = parse(data.encode("cp874"))
    assert report["rows"][0]["state"] == "completed" and report["rows"][0]["day"] == "2026-10-15"


def test_unrecognised_report_lists_headers_instead_of_importing_zero():
    with pytest.raises(ReportError, match="Headers found: Foo, Bar"):
        parse(b"Foo,Bar\n1,2\n")
    with pytest.raises(ReportError, match="no Sub ID column"):
        parse(b"Order id,Item Total Commission\nO1,3\n")
    # Optional-looking columns whose absence would corrupt totals are required.
    with pytest.raises(ReportError, match="no order status column"):
        parse(b"Order id,Item id,Item Total Commission,Sub_id1\nO1,A,3,s\n")
    with pytest.raises(ReportError, match="no item ID column"):
        parse(b"Order id,Order Status,Item Total Commission,Sub_id1\nO1,Pending,3,s\n")


def test_import_records_which_header_fed_each_field(tmp_path):
    affiliate = Affiliate(Store(tmp_path))
    record = affiliate.import_report("a.csv", CONVERSIONS.format(fb="a", yt="b").encode())
    assert record["matched"]["item_commission"] == "Item Total Commission"
    assert record["matched"]["sub_ids"].startswith("Sub_id1")


def test_import_upserts_status_and_attributes_by_sub_id(tmp_path):
    store = Store(tmp_path)
    affiliate = Affiliate(store)
    # Rows imported before the job's Sub IDs exist still match afterwards.
    job = store.create_job({"name": "Cup"})
    fb, yt = sub_id(job["id"], "facebook"), sub_id(job["id"], "youtube")
    first = affiliate.import_report("a.csv", CONVERSIONS.format(fb=fb.upper(), yt=yt).encode())
    assert (first["inserted"], first["updated"]) == (4, 0)
    again = affiliate.import_report("a.csv", CONVERSIONS.replace("O1,Pending", "O1,Completed").format(fb=fb, yt=yt).encode())
    assert (again["inserted"], again["updated"]) == (0, 1)
    channels = affiliate.job_view(job["id"])["channels"]
    assert channels["facebook"]["commission_completed"] == 1234.5
    assert channels["facebook"]["commission_cancelled"] == 5
    assert channels["facebook"]["orders"] == 1
    assert channels["youtube"]["commission_completed"] == 20
    assert affiliate.summary()["unattributed"]["commission_completed"] == 7


def test_same_item_fallback_reports_unattributed_orders(tmp_path):
    store = Store(tmp_path)
    affiliate = Affiliate(store)
    job = store.create_job({"name": "Other"})
    affiliate.update_product(job["id"], 0, {"product_url": "https://shopee.co.th/x-i.5.I9"})
    affiliate.import_report("a.csv", CONVERSIONS.format(fb="a", yt="b").encode())
    assert affiliate.job_view(job["id"])["product"]["item_id"] == ""  # non-numeric id is not a Shopee URL
    affiliate.update_product(job["id"], 1, {"product_url": "https://shopee.co.th/product/5/9"})
    data = "Order id,Order Status,Item id,Item Total Commission,Sub_id1\nO9,Completed,9,30,\n"
    affiliate.import_report("b.csv", data.encode())
    assert affiliate.job_view(job["id"])["same_item_unattributed"] == {"rows": 1, "commission": 30}


def test_product_snapshot_keeps_commission_history_and_revision_fence(tmp_path):
    store = Store(tmp_path)
    affiliate = Affiliate(store)
    job = store.create_job({"name": "Cup"})
    record = affiliate.update_product(job["id"], 0, {"commission_rate": "8", "campaign_ends": "2026-10-20"})
    record = affiliate.update_product(job["id"], record["revision"], {"commission_rate": "8"})
    record = affiliate.update_product(job["id"], record["revision"], {"commission_rate": "10.5"})
    assert [h["rate"] for h in record["commission_history"]] == [8, 10.5]
    with pytest.raises(Conflict):
        affiliate.update_product(job["id"], 0, {"category": "x"})
    with pytest.raises(Invalid):
        affiliate.update_product(job["id"], record["revision"], {"commission_rate": "150"})
    with pytest.raises(Invalid):
        affiliate.update_product(job["id"], record["revision"], {"campaign_ends": "20/10/2026"})


def test_post_validation(tmp_path):
    store = Store(tmp_path)
    affiliate = Affiliate(store)
    job = store.create_job({"name": "Cup"})
    other = prepared(store)
    with pytest.raises(Invalid):
        affiliate.add_post(job["id"], {"channel": "tiktok"})
    with pytest.raises(Invalid):
        affiliate.add_post(job["id"], {"channel": "facebook", "url": "javascript:alert(1)"})
    render = ready_render(store, other)
    store.set_render_result(render["id"], "ready", outputs={})
    with pytest.raises(Invalid, match="finished render of this job"):
        affiliate.add_post(job["id"], {"channel": "facebook", "render_id": render["id"]})
    post = affiliate.add_post(other["id"], {"channel": "youtube", "render_id": render["id"]})
    assert post["posted_on"] == date.today().isoformat()
    with pytest.raises(Invalid):
        affiliate.update_post(other["id"], post["id"], {"manual": {"clicks": "1.5"}})
    assert affiliate.update_post(other["id"], post["id"], {"manual": {"clicks": None}})["manual"] is None
    affiliate.delete_post(other["id"], post["id"])
    assert affiliate.posted_counts() == {}


def test_summary_classifies_by_posted_render_and_withholds_comparison(tmp_path):
    store = Store(tmp_path)
    affiliate = Affiliate(store)
    job = prepared(store)  # scene 0 is a Flow scene
    render = ready_render(store, job)
    store.set_render_result(render["id"], "ready", outputs={})
    post = affiliate.add_post(job["id"], {"channel": "facebook", "render_id": render["id"]})
    affiliate.update_post(job["id"], post["id"], {"manual": {"clicks": 4, "orders": 1, "commission": "12.5"}})
    # Editing the plan afterwards must not reclassify what was posted.
    current = store.get_job(job["id"])
    plan = {**current["plan"], "scenes": [{**s, "source": "still"} for s in current["plan"]["scenes"]]}
    store.save_plan(job["id"], current["revision"], plan)
    summary = affiliate.summary()
    row = summary["rows"][0]
    assert row["scene_kind"] == "flow"
    assert row["total"]["clicks"] == 4 and row["total"]["commission_completed"] == 12.5
    assert row["total"]["posts"] == 1 and summary["groups"]["channel"]["facebook"]["posts"] == 1
    assert row["channels"]["facebook"]["manual"] is True
    assert summary["groups"]["scene_kind"]["flow"]["products"] == 1
    assert summary["comparison"]["enough"] is False


def test_alerts_need_click_coverage_skip_shopee_and_dedupe(tmp_path):
    store = Store(tmp_path)
    affiliate = Affiliate(store)
    job = store.create_job({"name": "Cup"})
    fb = sub_id(job["id"], "facebook")
    affiliate.add_post(job["id"], {"channel": "facebook", "posted_on": "2026-10-01"})
    affiliate.add_post(job["id"], {"channel": "shopee", "posted_on": "2026-10-01"})
    today = date(2026, 10, 15)
    assert affiliate.due_alerts(today) == []  # no click report imported yet
    affiliate.import_report("c.csv", CLICKS.format(fb="nomatch").encode())
    alerts = affiliate.due_alerts(today)
    assert [a["milestone"] for a in alerts] == ["no_clicks"] and "facebook" in alerts[0]["detail"]
    affiliate.import_report("c2.csv", CLICKS.replace("C", "D").replace("Dlick", "Click").format(fb=fb).encode())
    assert affiliate.due_alerts(today) == []

    record = affiliate.update_product(job["id"], 0, {"campaign_ends": "2026-10-16", "campaign_name": "11.11"})
    assert [a["milestone"] for a in affiliate.due_alerts(today)] == ["campaign_ending"]
    assert affiliate.due_alerts(date(2026, 10, 17)) == []
    affiliate.update_product(job["id"], record["revision"], {"campaign_ends": "2026-10-30"})
    assert affiliate.due_alerts(today) == []

    affiliate.update_product(job["id"], record["revision"] + 1, {"campaign_ends": "2026-10-16"})
    assert affiliate.enqueue_alerts(today) == 1
    affiliate.enqueue_alerts(today)
    with store._tx() as db:
        assert db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 1


def test_alert_notification_text_is_thai_with_detail(tmp_path):
    from app.shop_worker import Worker
    store = Store(tmp_path)
    affiliate = Affiliate(store)
    job = store.create_job({"name": "Cup"})
    affiliate.add_post(job["id"], {"channel": "facebook"})
    affiliate.update_product(job["id"], 0, {"campaign_ends": date.today().isoformat(), "campaign_name": "Payday"})
    sent = []

    async def send(text):
        sent.append(text)
    affiliate.enqueue_alerts()
    assert asyncio.run(Worker(store, send=send).run_once()) is True
    assert sent == ["🛍 Cup: แคมเปญ affiliate ใกล้หมด\nPayday หมด " + date.today().isoformat()]
    with pytest.raises(Invalid):
        store.notify(job["id"], "no_clicks", "k")  # affiliate alerts must name their event


def test_api_routes_csrf_and_revenue_page(tmp_path, monkeypatch):
    from app.shop_api import create_app
    from fastapi.testclient import TestClient
    client = TestClient(create_app(tmp_path))
    session = client.get("/shop/api/session").json()
    headers = {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}
    job = client.post("/shop/api/jobs", json={"name": "Cup"}, headers=headers).json()
    files = {"file": ("c.csv", io.BytesIO(CONVERSIONS.format(fb="a", yt="b").encode()), "text/csv")}
    assert client.post("/shop/api/affiliate/imports", files=files).status_code == 403
    files = {"file": ("c.csv", io.BytesIO(CONVERSIONS.format(fb="a", yt="b").encode()), "text/csv")}
    assert client.post("/shop/api/affiliate/imports", files=files, headers=headers).json()["rows"] == 4
    bad = {"file": ("x.csv", io.BytesIO(b"Foo,Bar\n1,2\n"), "text/csv")}
    response = client.post("/shop/api/affiliate/imports", files=bad, headers=headers)
    assert response.status_code == 422 and "Foo" in response.json()["detail"]
    post = client.post(f"/shop/api/jobs/{job['id']}/posts", json={"channel": "facebook", "url": "https://fb.example/1"}, headers=headers)
    assert post.status_code == 201
    response = client.patch(f"/shop/api/jobs/{job['id']}/posts/{post.json()['id']}", json={"manual": {"clicks": "2"}}, headers=headers)
    assert response.json()["manual"]["clicks"] == 2
    assert client.put(f"/shop/api/jobs/{job['id']}/affiliate", json={"revision": 0, "category": "บ้าน"}, headers=headers).status_code == 200
    assert client.get("/shop/api/jobs").json()[0]["posts"] == 1
    assert client.get(f"/shop/api/jobs/{job['id']}").json()["revision"] == job["revision"]
    page = client.get("/shop/revenue")
    assert page.status_code == 200 and "สรุปรายได้ affiliate" in page.text and "Cup" in page.text
    assert "affiliate-panel" in client.get(f"/shop/{job['id']}").text
    assert client.delete(f"/shop/api/jobs/{job['id']}/posts/{post.json()['id']}", headers=headers).status_code == 204
