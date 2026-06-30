import i18n


def test_all_msg_types_render_for_every_nonthai_lang():
    params = dict(
        name="Aung", date="2026-06-24", status="leave", half=True,
        comp="0", leave="-1", kind_pos=False, bal_days="1", bal_amt="500",
        daily_rate="500", month=6, year=2026, period=1, amount="500",
        deduction_days="0", paid_by="ฟิก",
        end_date="2026-06-30", base_salary="15000",
    )
    msg_types = (
        "attendance", "payment", "daily_payment", "resign",
        "monthly", "monthly_probation_owed", "monthly_probation_clear",
        "cancel_attendance", "cancel_resign", "slip_image",
    )
    for mt in msg_types:
        for lang in ("my", "en", "lo", "km"):
            out = i18n.translate_block(mt, lang, **params)
            assert isinstance(out, str) and out.strip(), (mt, lang)


def test_thai_returns_none():
    assert i18n.translate_block("attendance", "th", name="x", date="d",
                                status="leave", half=False) is None


def test_unknown_lang_returns_none():
    assert i18n.translate_block("attendance", "zz", name="x", date="d",
                                status="leave", half=False) is None


def test_status_label_keys_exist_in_all_langs():
    for lang in ("my", "en", "lo", "km"):
        for st in ("leave", "compensatory"):
            assert st in i18n._STATUS[lang], (lang, st)
