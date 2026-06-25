"""Static reminder translations — replaces the MiMo-LLM translator.

Reminder texts are a small, nearly-fixed set (owner confirmed ~2-10 distinct
texts, rarely changes) so a hand-maintained dict beats an LLM call: no API
dependency, no failure modes, deterministic.

machine-generated (seeded from MiMo output already in production),
needs native-speaker review — same caveat as i18n.py.
"""

REMINDERS: dict[str, dict[str, str]] = {
    "🛏️ วันนี้เปลี่ยนผ้าปูที่นอนด้วยนะคะ": {
        "my": "ဒီနေ့ အိပ်ရာခင်း ပြောင်းပါ",
        "en": "Please change the bedsheets today.",
        "lo": "ກະລຸນາປ່ຽນຜ້າປູບ່ຽນມື້ນີ້",
        "km": "ថ្ងៃនេះ សូមផ្លាស់ប្តូរស្បៃក្បាលដេក",
    },
    "🚿 วันนี้ล้างห้องน้ำด้วยนะคะ": {
        "my": "ဒီနေ့ အိမ်သာကိုလည်း သန့်ရှင်းပါဦး။",
        "en": "Please clean the bathroom today as well.",
        "lo": "ມື້ນີ້ກະລຸນາລ້າງຫ້ອງນ້ຳເດີ.",
        "km": "ថ្ងៃនេះសូមសម្អាតបន្ទប់ទឹកផង.",
    },
}


def lookup(text: str) -> dict | None:
    return REMINDERS.get(text)
