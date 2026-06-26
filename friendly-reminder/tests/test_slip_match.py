import time
from app.slip_match import decide, PendingStore

OUT1 = [{"id": 10, "name": "iPhone 15", "installment_number": 3, "num_installments": 10, "amount": 3000.0}]
OUT2 = OUT1 + [{"id": 20, "name": "ตู้เย็น", "installment_number": 1, "num_installments": 6, "amount": 1500.0}]


def test_single_outstanding_image_attaches_and_pays():
    p = PendingStore()
    d = decide(OUT1, saved_slip_path="/data/slips/x.jpg", text=None, group_id="G", pending=p, now_ts=time.time())
    assert d.action == "attach_pay"
    assert d.payment_id == 10
    assert d.slip_path == "/data/slips/x.jpg"


def test_zero_outstanding_image_ignored_with_notice():
    p = PendingStore()
    d = decide([], saved_slip_path="/data/slips/x.jpg", text=None, group_id="G", pending=p, now_ts=time.time())
    assert d.action == "ignore"
    assert "ไม่มีงวดค้าง" in d.reply_text


def test_multi_outstanding_image_asks_and_stores_pending():
    p = PendingStore()
    d = decide(OUT2, saved_slip_path="/data/slips/y.jpg", text=None, group_id="G", pending=p, now_ts=100.0)
    assert d.action == "ask"
    assert "iPhone 15" in d.reply_text and "ตู้เย็น" in d.reply_text
    # pending now armed
    d2 = decide(OUT2, saved_slip_path=None, text="จ่ายตู้เย็นแล้ว", group_id="G", pending=p, now_ts=101.0)
    assert d2.action == "attach_pay"
    assert d2.payment_id == 20
    assert d2.slip_path == "/data/slips/y.jpg"


def test_text_without_pending_is_silent():
    p = PendingStore()
    d = decide(OUT2, saved_slip_path=None, text="จ่ายแล้ว", group_id="G", pending=p, now_ts=100.0)
    assert d.action == "ignore"
    assert d.reply_text is None


def test_pending_expires_after_ttl():
    p = PendingStore()
    p.put("G", "/data/slips/z.jpg", [10], 100.0)
    assert p.take("G", 100.0 + PendingStore.TTL + 1) is None
