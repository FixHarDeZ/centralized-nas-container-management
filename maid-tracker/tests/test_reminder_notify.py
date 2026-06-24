import json

import line_notify


def test_appends_only_active_langs():
    cache = json.dumps({"my": "ဆေး", "en": "Clean", "lo": "x", "km": "y"})
    out = line_notify._reminder_body("เตือน", "ล้างห้องน้ำ", cache, ["my"])
    assert "ล้างห้องน้ำ" in out
    assert "ဆေး" in out          # my appended
    assert "Clean" not in out     # en not active


def test_no_active_langs_thai_only():
    cache = json.dumps({"my": "ဆေး", "en": "Clean", "lo": "x", "km": "y"})
    out = line_notify._reminder_body("เตือน", "ล้างห้องน้ำ", cache, [])
    assert "ล้างห้องน้ำ" in out
    assert "ဆေး" not in out


def test_null_cache_thai_only():
    out = line_notify._reminder_body("เตือน", "ล้างห้องน้ำ", None, ["my"])
    assert "ล้างห้องน้ำ" in out and "─" not in out
