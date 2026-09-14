"""The religion gate, and the one way past it.

ADR 0011: religious subject matter is excluded from the first ten Stories. It is
the one category where being wrong produces not a bad video but an offensive
one, and under ADR 0010 nobody necessarily reads the prose before it renders.
Ten Stories is enough to see whether the Source note validator holds on material
the model knows well, before pointing it at material where errors are
unforgivable.

Like `RESULT_TOPIC` in shorts-factory, the gate lives in code rather than in the
prompt, and for the same reason: a prompt-level ban is a suggestion. It is
checked at the single point where a subject becomes a Story, because subjects
arrive by more than one route — typed by the human, picked from a Competitor
scan, chosen at random — and they all pass through there.
"""

from __future__ import annotations

import re

#: Matched against the subject line only. Deliberately blunt: a false positive
#: costs one retyped subject, a false negative costs a published video.
RELIGIOUS = re.compile(
    "|".join(
        (
            r"พระพุทธ", r"พระเจ้า", r"พระธรรม", r"พระสงฆ์", r"พระภิกษุ",
            r"นรก", r"สวรรค์", r"ชาติหน้า", r"กรรมเก่า", r"บุญกรรม",
            r"ศาสนา", r"พุทธ", r"คริสต์", r"อิสลาม", r"ฮินดู", r"ซิกข์",
            r"พระคัมภีร์", r"อัลกุรอาน", r"ไบเบิล", r"พระไตรปิฎก",
            r"เทพเจ้า", r"เทวดา", r"นิพพาน", r"วิญญาณศักดิ์สิทธิ์",
            r"ปาฏิหาริย์", r"บาปบุญ", r"ทำบุญ", r"สังฆทาน",
        ),
    ),
)


class Blocked(Exception):
    """Raised instead of returning a flag: a blocked subject must not be able to
    continue by accident down a path that ignored a boolean."""


def check(subject: str, stories_published: int, gate_until: int) -> None:
    """Raise `Blocked` if this subject may not become a Story yet.

    A leading `!` overrides the gate, matching the escape hatch shorts-factory
    uses on `RESULT_TOPIC`. The override is for the human at the keyboard; it is
    never added by the bot's own automatic paths.
    """
    if subject.startswith("!"):
        return
    if stories_published >= gate_until:
        return
    if RELIGIOUS.search(subject):
        raise Blocked(
            f"หัวข้อแนวศาสนายังไม่เปิด — เปิดหลังทำครบ {gate_until} Story "
            f"(ตอนนี้ {stories_published}) ตาม docs/adr/0011\n"
            f"ถ้าตั้งใจจริง ใส่ ! นำหน้าหัวข้อ",
        )


def strip_override(subject: str) -> str:
    """The `!` is an instruction to the gate, not part of the subject."""
    return subject[1:].strip() if subject.startswith("!") else subject
