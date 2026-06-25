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
    "🚗 วันนี้ล้างรถด้วยนะคะ": {
        "my": "ဒီနေ့ ကားဆေးပေးပါဦး။",
        "en": "Please wash the car today.",
        "lo": "ມື້ນີ້ກະລຸນາລ້າງລົດແດ່ເດີ້.",
        "km": "ថ្ងៃនេះសូមលាងឡានផង។",
    },
    "🏡 วันนี้ทำความสะอาดรอบบ้านด้วยนะคะ": {
        "my": "ဒီနေ့ အိမ်ပတ်ပတ်လည်ကို သန့်ရှင်းရေးလုပ်ပေးပါ။",
        "en": "Please clean around the house today.",
        "lo": "ມື້ນີ້ກະລຸນາອະນາໄມອ້ອມເຮືອນແດ່ເດີ້.",
        "km": "ថ្ងៃនេះសូមសម្អាតជុំវិញផ្ទះផង។",
    },
    "🧸 วันนี้ทำความสะอาดของเล่นด้วยนะคะ": {
        "my": "ဒီနေ့ ကစားစရာတွေကို သန့်ရှင်းရေးလုပ်ပေးပါ။",
        "en": "Please clean the toys today.",
        "lo": "ມື້ນີ້ກະລຸນາອະນາໄມເຄື່ອງຫຼິ້ນແດ່ເດີ້.",
        "km": "ថ្ងៃនេះសូមសម្អាតប្រដាប់ក្មេងលេងផង។",
    },
    "🧺 วันนี้ซักผ้าด้วยนะคะ": {
        "my": "ဒီနေ့ အဝတ်လျှော်ပေးပါဦး။",
        "en": "Please do the laundry today.",
        "lo": "ມື້ນີ້ກະລຸນາຊັກເຄື່ອງແດ່ເດີ້.",
        "km": "ថ្ងៃនេះសូមបោកខោអាវផង។",
    },
    "🧓 วันนี้ทำความสะอาดห้องคุณตา/คุณยายด้วยนะคะ": {
        "my": "ဒီနေ့ အဘိုး/အဘွားရဲ့ အခန်းကို သန့်ရှင်းရေးလုပ်ပေးပါ။",
        "en": "Please clean grandpa's/grandma's room today.",
        "lo": "ມື້ນີ້ກະລຸນາອະນາໄມຫ້ອງຄຸນຕາ/ຄຸນຍາຍແດ່ເດີ້.",
        "km": "ថ្ងៃនេះសូមសម្អាតបន្ទប់លោកតា/លោកយាយផង។",
    },
}


def lookup(text: str) -> dict | None:
    return REMINDERS.get(text)
