# LINE webhook keyword lists
# Edit this file to add / remove trigger phrases for leave, compensatory, and half-day detection.

LEAVE_KEYWORDS = [
    # Thai
    "ขอลา", "ลาวันนี้", "วันนี้ขอลา", "วันนี้ลา", "ลาวันนี้นะ",
    "ขอหยุด", "หยุดวันนี้", "วันนี้หยุด", "วันนี้ขอหยุด",
    "ลาครึ่งวัน", "ลาครึ่ง",
    # English
    "take leave", "taking leave", "day off", "off today", "leave today",
    "on leave", "half day leave", "half day off",
]

COMP_KEYWORDS = [
    # Thai
    "ทำชดเชย", "ชดเชยวันนี้", "วันนี้ชดเชย", "วันนี้ทำชดเชย",
    "ทำงานวันหยุด", "ทำงานวันอาทิตย์", "มาทำงานวันนี้",
    "ชดเชยครึ่งวัน", "ชดเชยครึ่ง",
    # English
    "comp day", "compensatory", "working on holiday", "working today",
    "work today", "worked today",
]

HALF_DAY_KEYWORDS = [
    # Thai
    "ครึ่งวัน", "ครึ่งวันเช้า", "ครึ่งวันบ่าย",
    # English
    "half day", "half-day",
]
