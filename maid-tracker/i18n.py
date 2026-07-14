"""Static translations for maid-facing LINE notifications.

Thai is the primary message (built in line_notify.py); this module produces the
appended translated block for non-Thai maids. Fragments (status labels, balance
block) are defined once per language and reused across message types.

⚠️ my / lo / km strings are machine-generated and NOT verified by a native
speaker. en is self-verified. Have a native speaker review before relying on
the Burmese / Lao / Khmer output.
"""

LANGS = ("th", "my", "en", "lo", "km")

# Status labels (emoji kept; only the word is translated).
_STATUS = {
    "en": {"leave": "🔴 Leave", "compensatory": "🟢 Comp day"},
    # machine-generated, needs native-speaker review
    "my": {"leave": "🔴 ခွင့်ယူ", "compensatory": "🟢 အပိုဆောင်းရက်"},
    # machine-generated, needs native-speaker review
    "lo": {"leave": "🔴 ລາພັກ", "compensatory": "🟢 ມື້ຊົດເຊີຍ"},
    # machine-generated, needs native-speaker review
    "km": {"leave": "🔴 ច្បាប់ឈប់", "compensatory": "🟢 ថ្ងៃសង"},
}

_HALF = {
    "en": {True: " (half day)", False: " (full day)"},
    "my": {True: " (နေ့ဝက်)", False: " (တစ်နေ့)"},          # machine-generated
    "lo": {True: " (ເຄິ່ງມື້)", False: " (ເຕັມມື້)"},        # machine-generated
    "km": {True: " (កន្លះថ្ងៃ)", False: " (ពេញមួយថ្ងៃ)"},   # machine-generated
}

# Per-message field labels. {} placeholders filled with caller-formatted values.
_MSG = {
    "en": {
        "attendance": "📋 Work record — {name}\n📅 {date}: {status}\n\n{balance}",
        "payment": "💰 Salary paid — {name}\n📅 {month}/{year} period {period}\n💵 ฿{amount}\n{payer}{balance}",
        "daily_payment": "💵 Daily pay — {name}\n📅 {date}: ฿{amount}\n{payer}",
        "resign": "🚪 Resignation — {name}\n📅 Last day: {end_date}\n💵 Total payout: ฿{final}",
        "balance": "📊 Balance: comp {comp} / leave {leave} days\n⚖️ {kind}: {bal_days} days ≈ ฿{bal_amt} (฿{daily_rate}/day)",
        "balance_query": "📊 Accumulated — {name}\n\n📅 Days worked: {days} days\n💵 Total paid: ฿{amount}\n(฿{daily_rate}/day)",
        "monthly": "📊 {name}: comp {comp} / leave {leave} days\n  ⚖️ {kind} {bal_days} days ≈ ฿{bal_amt}",
        "monthly_probation_owed": "📊 {name}: 💵 outstanding ฿{amount}",
        "monthly_probation_clear": "📊 {name}: ✅ no outstanding",
        "cancel_attendance": "↩️ Cancelled — {name}\n📅 {date}: cancel {status}\n\n{balance}",
        "cancel_resign": "↩️ Resignation cancelled — {name}",
        "slip_image": "📎 Transfer slip — {name}",
        "daily_pay_all": "💰 All outstanding daily wages paid — {name}\n📅 {days} days\n💵 Total ฿{amount}\n{payer}",
        "kind_pos": "credit", "kind_neg": "owed", "payer": "  Paid by: {paid_by}\n",
    },
    # machine-generated, needs native-speaker review
    "my": {
        "attendance": "📋 အလုပ်မှတ်တမ်း — {name}\n📅 {date}: {status}\n\n{balance}",
        "payment": "💰 လစာပေးပြီး — {name}\n📅 {month}/{year} အပိုင်း {period}\n💵 ฿{amount}\n{payer}{balance}",
        "daily_payment": "💵 နေ့စဉ်လုပ်ခ — {name}\n📅 {date}: ฿{amount}\n{payer}",
        "resign": "🚪 အလုပ်ထွက် — {name}\n📅 နောက်ဆုံးနေ့: {end_date}\n💵 စုစုပေါင်းပေးချေငွေ: ฿{final}",
        "balance": "📊 လက်ကျန်: အပို {comp} / ခွင့် {leave} ရက်\n⚖️ {kind}: {bal_days} ရက် ≈ ฿{bal_amt} (฿{daily_rate}/ရက်)",
        "balance_query": "📊 စုပေါင်း — {name}\n\n📅 အလုပ်လုပ်သည့်ရက်: {days} ရက်\n💵 ပေးပြီးငွေ: ฿{amount}\n(฿{daily_rate}/ရက်)",
        "monthly": "📊 {name}: အပို {comp} / ခွင့် {leave} ရက်\n  ⚖️ {kind} {bal_days} ရက် ≈ ฿{bal_amt}",
        "monthly_probation_owed": "📊 {name}: 💵 ပေးရန်ကျန် ฿{amount}",
        "monthly_probation_clear": "📊 {name}: ✅ ပေးရန်မကျန်ပါ",
        "cancel_attendance": "↩️ ပယ်ဖျက် — {name}\n📅 {date}: {status} ပယ်ဖျက်\n\n{balance}",
        "cancel_resign": "↩️ အလုပ်ထွက်ခြင်း ပယ်ဖျက် — {name}",
        "slip_image": "📎 ငွေလွှဲ slip — {name}",
        "daily_pay_all": "💰 ကျန်ရှိနေ့စဉ်လုပ်ခ အားလုံးပေးပြီး — {name}\n📅 {days} ရက်\n💵 စုစုပေါင်း ฿{amount}\n{payer}",
        "kind_pos": "အကြွေး", "kind_neg": "ပေးရန်", "payer": "  ပေးသူ: {paid_by}\n",
    },
    # machine-generated, needs native-speaker review
    "lo": {
        "attendance": "📋 ບັນທຶກການເຮັດວຽກ — {name}\n📅 {date}: {status}\n\n{balance}",
        "payment": "💰 ຈ່າຍເງິນເດືອນແລ້ວ — {name}\n📅 {month}/{year} ງວດ {period}\n💵 ฿{amount}\n{payer}{balance}",
        "daily_payment": "💵 ຄ່າຈ້າງລາຍວັນ — {name}\n📅 {date}: ฿{amount}\n{payer}",
        "resign": "🚪 ລາອອກ — {name}\n📅 ມື້ສຸດທ້າຍ: {end_date}\n💵 ຍອດຈ່າຍລວມ: ฿{final}",
        "balance": "📊 ຍອດ: ຊົດເຊີຍ {comp} / ລາ {leave} ມື້\n⚖️ {kind}: {bal_days} ມື້ ≈ ฿{bal_amt} (฿{daily_rate}/ມື້)",
        "balance_query": "📊 ລວມ — {name}\n\n📅 ມື້ເຮັດວຽກ: {days} ມື້\n💵 ຈ່າຍແລ້ວ: ฿{amount}\n(฿{daily_rate}/ມື້)",
        "monthly": "📊 {name}: ຊົດເຊີຍ {comp} / ລາ {leave} ມື້\n  ⚖️ {kind} {bal_days} ມື້ ≈ ฿{bal_amt}",
        "monthly_probation_owed": "📊 {name}: 💵 ຄ້າງຈ່າຍ ฿{amount}",
        "monthly_probation_clear": "📊 {name}: ✅ ບໍ່ມີຍອດຄ້າງຈ່າຍ",
        "cancel_attendance": "↩️ ຍົກເລີກ — {name}\n📅 {date}: ຍົກເລີກ {status}\n\n{balance}",
        "cancel_resign": "↩️ ຍົກເລີກການລາອອກ — {name}",
        "slip_image": "📎 ສະລິບໂອນເງິນ — {name}",
        "daily_pay_all": "💰 ຈ່າຍຄ່າຈ້າງລາຍວັນຄ້າງທັງໝົດແລ້ວ — {name}\n📅 {days} ມື້\n💵 ລວມ ฿{amount}\n{payer}",
        "kind_pos": "ເຄຣດິດ", "kind_neg": "ຄ້າງ", "payer": "  ຜູ້ຈ່າຍ: {paid_by}\n",
    },
    # machine-generated, needs native-speaker review
    "km": {
        "attendance": "📋 កំណត់ត្រាការងារ — {name}\n📅 {date}: {status}\n\n{balance}",
        "payment": "💰 បានបើកប្រាក់ខែ — {name}\n📅 {month}/{year} វគ្គ {period}\n💵 ฿{amount}\n{payer}{balance}",
        "daily_payment": "💵 ប្រាក់ឈ្នួលប្រចាំថ្ងៃ — {name}\n📅 {date}: ฿{amount}\n{payer}",
        "resign": "🚪 លាឈប់ — {name}\n📅 ថ្ងៃចុងក្រោយ: {end_date}\n💵 ប្រាក់សរុបត្រូវបង់: ฿{final}",
        "balance": "📊 សមតុល្យ: សង {comp} / ឈប់ {leave} ថ្ងៃ\n⚖️ {kind}: {bal_days} ថ្ងៃ ≈ ฿{bal_amt} (฿{daily_rate}/ថ្ងៃ)",
        "balance_query": "📊 សរុប — {name}\n\n📅 ថ្ងៃធ្វើការ: {days} ថ្ងៃ\n💵 បានបង់: ฿{amount}\n(฿{daily_rate}/ថ្ងៃ)",
        "monthly": "📊 {name}: សង {comp} / ឈប់ {leave} ថ្ងៃ\n  ⚖️ {kind} {bal_days} ថ្ងៃ ≈ ฿{bal_amt}",
        "monthly_probation_owed": "📊 {name}: 💵 នៅជំពាក់ ฿{amount}",
        "monthly_probation_clear": "📊 {name}: ✅ គ្មានបំណុលត្រូវបង់",
        "cancel_attendance": "↩️ បានបោះបង់ — {name}\n📅 {date}: បោះបង់ {status}\n\n{balance}",
        "cancel_resign": "↩️ បានបោះបង់ការលាឈប់ — {name}",
        "slip_image": "📎 វិក្កយប័ត្រផ្ទេរប្រាក់ — {name}",
        "daily_pay_all": "💰 បានបង់ប្រាក់ឈ្នួលប្រចាំថ្ងៃដែលនៅជំពាក់ទាំងអស់ — {name}\n📅 {days} ថ្ងៃ\n💵 សរុប ฿{amount}\n{payer}",
        "kind_pos": "ឥណទាន", "kind_neg": "ជំពាក់", "payer": "  អ្នកបង់: {paid_by}\n",
    },
}


# Pass-probation congratulations (separate template family: needs schedule/leave
# sub-lines that don't fit translate_block's flat placeholder set).
_PASS_PROBATION = {
    "en": {
        "msg": (
            "🎉 Congratulations {name}! You passed probation!\n"
            "✅ Passed on: {pass_date}\n"
            "📅 Monthly salary starts: {start}\n"
            "\n"
            "What you will receive:\n"
            "💰 Salary ฿{salary}/month\n"
            "{sched}\n"
            "{leave}"
        ),
        "sched_biweekly": "💳 Paid twice a month — on the 15th and at month end",
        "sched_monthly": "💳 Paid once a month — at month end",
        "leave_monthly": "🌴 {days} paid leave days per month",
        "leave_sunday": "🌴 Every Sunday off (paid)",
        "tail_daily": "⏳ Until then, daily pay continues as before",
    },
    # machine-generated, needs native-speaker review
    "my": {
        "msg": (
            "🎉 ဂုဏ်ယူပါတယ် {name}! အလုပ်စမ်းသပ်ကာလ အောင်မြင်ပါပြီ!\n"
            "✅ အောင်မြင်သည့်နေ့: {pass_date}\n"
            "📅 လစာစတင်မည့်နေ့: {start}\n"
            "\n"
            "ရရှိမည့်အရာများ:\n"
            "💰 လစာ ฿{salary}/လ\n"
            "{sched}\n"
            "{leave}"
        ),
        "sched_biweekly": "💳 တစ်လ ၂ ကြိမ် — ၁၅ ရက်နေ့နှင့် လကုန်",
        "sched_monthly": "💳 တစ်လ ၁ ကြိမ် — လကုန်",
        "leave_monthly": "🌴 တစ်လ {days} ရက် လစာဖြင့် ခွင့်ရက်",
        "leave_sunday": "🌴 တနင်္ဂနွေနေ့တိုင်း နားရက် (လစာရ)",
        "tail_daily": "⏳ ထိုနေ့မတိုင်မီ နေ့စဉ်လုပ်ခ ဆက်လက်ရရှိမည်",
    },
    # machine-generated, needs native-speaker review
    "lo": {
        "msg": (
            "🎉 ຊົມເຊີຍ {name}! ຜ່ານການທົດລອງງານແລ້ວ!\n"
            "✅ ຜ່ານວັນທີ: {pass_date}\n"
            "📅 ເລີ່ມເງິນເດືອນປະຈຳ: {start}\n"
            "\n"
            "ສິ່ງທີ່ຈະໄດ້ຮັບ:\n"
            "💰 ເງິນເດືອນ ฿{salary}/ເດືອນ\n"
            "{sched}\n"
            "{leave}"
        ),
        "sched_biweekly": "💳 ຈ່າຍເດືອນລະ 2 ຄັ້ງ — ວັນທີ 15 ແລະ ທ້າຍເດືອນ",
        "sched_monthly": "💳 ຈ່າຍເດືອນລະ 1 ຄັ້ງ — ທ້າຍເດືອນ",
        "leave_monthly": "🌴 ພັກໄດ້ເດືອນລະ {days} ມື້ (ໄດ້ຄ່າຈ້າງ)",
        "leave_sunday": "🌴 ພັກທຸກວັນອາທິດ (ໄດ້ຄ່າຈ້າງ)",
        "tail_daily": "⏳ ກ່ອນຮອດມື້ນັ້ນ ຍັງຈ່າຍລາຍວັນຕາມເດີມ",
    },
    # machine-generated, needs native-speaker review
    "km": {
        "msg": (
            "🎉 អបអរសាទរ {name}! បានឆ្លងផុតការសាកល្បងការងារហើយ!\n"
            "✅ ថ្ងៃឆ្លងផុត: {pass_date}\n"
            "📅 ចាប់ផ្តើមប្រាក់ខែ: {start}\n"
            "\n"
            "អ្វីដែលនឹងទទួលបាន:\n"
            "💰 ប្រាក់ខែ ฿{salary}/ខែ\n"
            "{sched}\n"
            "{leave}"
        ),
        "sched_biweekly": "💳 បើកប្រាក់ខែ 2 ដងក្នុងមួយខែ — ថ្ងៃទី 15 និងចុងខែ",
        "sched_monthly": "💳 បើកប្រាក់ខែ 1 ដងក្នុងមួយខែ — ចុងខែ",
        "leave_monthly": "🌴 ថ្ងៃឈប់សម្រាក {days} ថ្ងៃក្នុងមួយខែ (មានប្រាក់ឈ្នួល)",
        "leave_sunday": "🌴 ឈប់សម្រាករៀងរាល់ថ្ងៃអាទិត្យ (មានប្រាក់ឈ្នួល)",
        "tail_daily": "⏳ មុនថ្ងៃនោះ នៅតែបើកប្រាក់ប្រចាំថ្ងៃដូចដើម",
    },
}


def pass_probation_block(
    lang, *, name, pass_date, start, salary, schedule, holiday_mode, leave_days,
    daily_until_start=False,
):
    """Translated congratulations block for a maid who passed probation.
    Returns None for Thai / unknown languages (Thai message is built in line_notify).
    """
    if lang == "th" or lang not in _PASS_PROBATION:
        return None
    m = _PASS_PROBATION[lang]
    sched = m["sched_monthly"] if schedule == "monthly" else m["sched_biweekly"]
    leave = (
        m["leave_monthly"].format(days=leave_days)
        if holiday_mode == "monthly"
        else m["leave_sunday"]
    )
    msg = m["msg"].format(
        name=name, pass_date=pass_date, start=start, salary=salary,
        sched=sched, leave=leave,
    )
    if daily_until_start:
        msg += "\n" + m["tail_daily"]
    return msg


def _balance_block_tr(lang, *, comp, leave, kind_pos, bal_days, bal_amt, daily_rate):
    m = _MSG[lang]
    kind = m["kind_pos"] if kind_pos else m["kind_neg"]
    return m["balance"].format(
        comp=comp, leave=leave, kind=kind,
        bal_days=bal_days, bal_amt=bal_amt, daily_rate=daily_rate,
    )


def translate_block(msg_type, lang, **p):
    if lang == "th" or lang not in _MSG:
        return None
    m = _MSG[lang]
    status = (
        _STATUS[lang].get(p["status"], p["status"]) + _HALF[lang][p["half"]]
        if "status" in p
        else ""
    )
    kind = (m["kind_pos"] if p["kind_pos"] else m["kind_neg"]) if "kind_pos" in p else ""
    balance = ""
    if "daily_rate" in p and "bal_days" in p:
        balance = _balance_block_tr(
            lang, comp=p["comp"], leave=p["leave"], kind_pos=p["kind_pos"],
            bal_days=p["bal_days"], bal_amt=p["bal_amt"], daily_rate=p["daily_rate"],
        )
    payer = m["payer"].format(paid_by=p["paid_by"]) if p.get("paid_by") else ""
    return m[msg_type].format(
        name=p.get("name", ""), date=p.get("date", ""), status=status,
        balance=balance, month=p.get("month", ""), year=p.get("year", ""),
        period=p.get("period", ""), amount=p.get("amount", ""), payer=payer,
        end_date=p.get("end_date", ""), final=p.get("final", ""),
        days=p.get("days", ""), daily_rate=p.get("daily_rate", ""),
        comp=p.get("comp", ""), leave=p.get("leave", ""), kind=kind,
        bal_days=p.get("bal_days", ""), bal_amt=p.get("bal_amt", ""),
    )
