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
    "km": {"leave": "🔴 ច្បាប់ឈប់", "compensatory": "🟢 ថ្ងៃសងសង"},
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
        "kind_pos": "credit", "kind_neg": "owed", "payer": "  Paid by: {paid_by}\n",
    },
    # machine-generated, needs native-speaker review
    "my": {
        "attendance": "📋 အလုပ်မှတ်တမ်း — {name}\n📅 {date}: {status}\n\n{balance}",
        "payment": "💰 လစာပေးပြီး — {name}\n📅 {month}/{year} အပိုင်း {period}\n💵 ฿{amount}\n{payer}{balance}",
        "daily_payment": "💵 နေ့စဉ်လုပ်ခ — {name}\n📅 {date}: ฿{amount}\n{payer}",
        "resign": "🚪 အလုပ်ထွက် — {name}\n📅 နောက်ဆုံးနေ့: {end_date}\n💵 စုစုပေါင်းပေးချေငွေ: ฿{final}",
        "balance": "📊 လက်ကျန်: အပို {comp} / ခွင့် {leave} ရက်\n⚖️ {kind}: {bal_days} ရက် ≈ ฿{bal_amt} (฿{daily_rate}/ရက်)",
        "kind_pos": "အကြွေး", "kind_neg": "ပေးရန်", "payer": "  ပေးသူ: {paid_by}\n",
    },
    # machine-generated, needs native-speaker review
    "lo": {
        "attendance": "📋 ບັນທຶກການເຮັດວຽກ — {name}\n📅 {date}: {status}\n\n{balance}",
        "payment": "💰 ຈ່າຍເງິນເດືອນແລ້ວ — {name}\n📅 {month}/{year} ງວດ {period}\n💵 ฿{amount}\n{payer}{balance}",
        "daily_payment": "💵 ຄ່າຈ້າງລາຍວັນ — {name}\n📅 {date}: ฿{amount}\n{payer}",
        "resign": "🚪 ລາອອກ — {name}\n📅 ມື້ສຸດທ້າຍ: {end_date}\n💵 ຍອດຈ່າຍລວມ: ฿{final}",
        "balance": "📊 ຍອດ: ຊົດເຊີຍ {comp} / ລາ {leave} ມື້\n⚖️ {kind}: {bal_days} ມື້ ≈ ฿{bal_amt} (฿{daily_rate}/ມື້)",
        "kind_pos": "ເຄຣດິດ", "kind_neg": "ຄ້າງ", "payer": "  ຜູ້ຈ່າຍ: {paid_by}\n",
    },
    # machine-generated, needs native-speaker review
    "km": {
        "attendance": "📋 កំណត់ត្រាការងារ — {name}\n📅 {date}: {status}\n\n{balance}",
        "payment": "💰 បានបើកប្រាក់ខែ — {name}\n📅 {month}/{year} វគ្គ {period}\n💵 ฿{amount}\n{payer}{balance}",
        "daily_payment": "💵 ប្រាក់ឈ្នួលប្រចាំថ្ងៃ — {name}\n📅 {date}: ฿{amount}\n{payer}",
        "resign": "🚪 លាឈប់ — {name}\n📅 ថ្ងៃចុងក្រោយ: {end_date}\n💵 ប្រាក់សរុបត្រូវបង់: ฿{final}",
        "balance": "📊 សមតុល្យ: សង {comp} / ឈប់ {leave} ថ្ងៃ\n⚖️ {kind}: {bal_days} ថ្ងៃ ≈ ฿{bal_amt} (฿{daily_rate}/ថ្ងៃ)",
        "kind_pos": "ឥណទាន", "kind_neg": "ជំពាក់", "payer": "  អ្នកបង់: {paid_by}\n",
    },
}


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
    balance = ""
    if "bal_days" in p:
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
    )
