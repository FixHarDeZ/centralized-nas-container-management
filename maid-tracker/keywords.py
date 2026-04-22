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

BALANCE_KEYWORDS = [
    # Thai
    "ยอดสะสม", "ยอดคงเหลือ", "ยอดลา", "เช็คยอด", "ดูยอด", "ยอดชดเชย", "แสดงยอด",
    # English
    "balance", "check balance", "my balance", "leave balance",
]

PAYMENT_KEYWORDS = [
    # Thai
    "จ่ายแล้ว", "จ่ายเงินแล้ว", "จ่ายเงินเดือนแล้ว", "โอนแล้ว", "จ่ายค่าแรงแล้ว",
    "จ่ายเงินให้", "โอนเงินแล้ว",
    # English
    "paid", "salary paid", "payment done", "transferred",
]

PAYMENT_PERIOD1_KEYWORDS = [
    # Thai — กลางเดือน / รอบแรก
    "กลางเดือน", "รอบแรก", "รอบ 1", "รอบหนึ่ง", "งวดแรก", "งวด 1",
    # English
    "mid month", "period 1", "first period", "first half",
]

PAYMENT_PERIOD2_KEYWORDS = [
    # Thai — ปลายเดือน / รอบสอง
    "ปลายเดือน", "รอบสอง", "รอบ 2", "สิ้นเดือน", "งวดสอง", "งวด 2",
    # English
    "end of month", "period 2", "second period", "second half",
]

PAYMENT_BOTH_KEYWORDS = [
    # Thai — ทั้งสองรอบ
    "ทั้งเดือน", "ทั้งคู่", "ทั้งสองรอบ", "ทั้งสองงวด", "ทั้งหมด", "ครบทั้งเดือน",
    # English
    "both", "both periods", "full month",
]
