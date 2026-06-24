import i18n

SEP = "\n\n─────────\n"


def _compose(thai_msg, language, msg_type, **params):
    """Mirror the append rule used in line_notify._append_tr."""
    if language != "th":
        block = i18n.translate_block(msg_type, language, **params)
        if block:
            return thai_msg + SEP + block
    return thai_msg


def test_thai_unchanged():
    assert _compose("ไทย", "th", "attendance") == "ไทย"


def test_my_appends_block():
    out = _compose("ไทย", "my", "attendance", name="Aung",
                   date="2026-06-24", status="leave", half=True)
    assert out.startswith("ไทย" + SEP)
    assert "Aung" in out
