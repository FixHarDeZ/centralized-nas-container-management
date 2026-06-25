import reminder_i18n as ri


def test_known_text_returns_all_four_langs():
    out = ri.lookup("🚿 วันนี้ล้างห้องน้ำด้วยนะคะ")
    assert out is not None
    assert set(out.keys()) == {"my", "en", "lo", "km"}
    assert all(isinstance(v, str) and v for v in out.values())


def test_second_seeded_text_also_resolves():
    out = ri.lookup("🛏️ วันนี้เปลี่ยนผ้าปูที่นอนด้วยนะคะ")
    assert out is not None
    assert set(out.keys()) == {"my", "en", "lo", "km"}
    assert all(isinstance(v, str) and v for v in out.values())


def test_unknown_text_returns_none():
    assert ri.lookup("ไม่มีในดิก ข้อความสุ่มที่ไม่ตรงกับอะไรเลย") is None
