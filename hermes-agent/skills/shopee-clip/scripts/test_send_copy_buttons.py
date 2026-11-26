import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("send_copy_buttons", os.path.join(HERE, "send_copy_buttons.py"))
scb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scb)

LINK = "https://s.shopee.co.th/abc"


def test_hook_adds_a_third_button_and_a_text_block():
    body, want = scb.build("#a #b", LINK, "1", "Game", "ใครเล่นจบแล้วต้องลองโหมดใหม่")
    kb = body["reply_markup"]["inline_keyboard"]
    assert [r[0]["text"] for r in kb] == ["🛒 Copy ลิงก์ตะกร้า", "#️⃣ Copy hashtags", "🪝 Copy hook"]
    assert want == [LINK, "#a #b", "ใครเล่นจบแล้วต้องลองโหมดใหม่"]
    assert "🪝 Hook:\nใครเล่นจบแล้วต้องลองโหมดใหม่" in body["text"]


def test_no_hook_keeps_the_two_buttons():
    """`clipjob.py mirror` resends deliveries made before the hook button."""
    body, want = scb.build("#a", LINK, "1")
    assert want == [LINK, "#a"] and "Hook" not in body["text"]


def test_limits():
    with pytest.raises(ValueError):
        scb.build("#a", "http://x", "1")
    with pytest.raises(ValueError):
        scb.build("#a", LINK, "1", "", "ก" * 257)
