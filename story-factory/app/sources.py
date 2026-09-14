"""The Source note rule, enforced in code.

ADR 0010 accepts that nobody is required to read a Story's prose before it is
rendered. That makes this the entire factual safety net, which is why it is a
validator and not a line in the prompt: the `RESULT_TOPIC` lesson from
shorts-factory is that a model asked nicely not to invent facts invents them
anyway, in the same shape, every time.

The rule a machine can actually check is not "is this true" but "is this stated
as if it were established". So a Chapter arrives as an ordered list of passages,
each either carrying a Source note or not, and:

  * a passage with a Source note may state its claim as fact;
  * a passage without one must be voiced as hearsay — "เล่ากันว่า" and friends;
  * a passage without one may not contain a figure at all. Fabricated numbers
    and dates were the concrete failure mode measured in shorts-factory, and no
    amount of hedging makes an invented year harmless.

A Chapter that breaks any of these is rejected and rewritten without asking the
human.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Ways Thai narration marks something as told rather than known. Kept as an
#: explicit list rather than a loose regex: the point is to force the model into
#: a small set of phrasings the ear recognises immediately as hearsay.
HEARSAY_MARKERS = (
    "เล่ากันว่า",
    "ว่ากันว่า",
    "มีเรื่องเล่าว่า",
    "เชื่อกันว่า",
    "บางคนบอกว่า",
    "ตำนานเล่าว่า",
    "มีคนเล่าว่า",
)

#: Arabic digits, Thai digits, and Buddhist/Christian era markers. A bare figure
#: in an unsourced passage is the failure this catches.
_FIGURE = re.compile(r"[0-9๐-๙]|พ\.ศ\.|ค\.ศ\.")


@dataclass(frozen=True)
class Passage:
    """One stretch of narration and the note behind it, if any."""

    text: str
    #: The reference found during research. Empty means unsourced — not
    #: forbidden, just restricted in how it may be voiced.
    source: str = ""

    @property
    def sourced(self) -> bool:
        return bool(self.source.strip())


@dataclass
class Verdict:
    ok: bool
    problems: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:  # so callers can write `if verdict:`
        return self.ok


def _is_hearsay(text: str) -> bool:
    return any(marker in text for marker in HEARSAY_MARKERS)


def check(passages: list[Passage], limit: int | None = None) -> Verdict:
    """Validate one Chapter's passages. Returns every problem, not just the
    first: the rewrite prompt is more useful when it lists them all.

    `limit` is the speech request cap in bytes. An unbroken run longer than the
    cap has no sentence boundary to split on and `tts.voice_chapter` refuses it
    — so it is checked here, where a rewrite is still available, rather than
    half an hour later where it is a lost Story.
    """
    problems: list[str] = []

    for index, passage in enumerate(passages, start=1):
        if limit is not None:
            from . import chunking

            if any(c.forced for c in chunking.split(passage.text, limit)):
                problems.append(
                    f"passage {index}: ประโยคเดียวยาวเกิน {limit} ไบต์ "
                    f"หั่นเป็นหลายประโยคสั้นลง",
                )

        if passage.sourced:
            continue
        if _FIGURE.search(passage.text):
            problems.append(
                f"passage {index}: states a figure with no Source note — "
                f"drop the number or find a source",
            )
        if not _is_hearsay(passage.text):
            problems.append(
                f"passage {index}: unsourced claim stated as fact — voice it as "
                f"hearsay, e.g. {HEARSAY_MARKERS[0]}",
            )

    return Verdict(ok=not problems, problems=problems)


def rewrite_note(verdict: Verdict) -> str:
    """The correction fed back to the model. Phrased as a rule restated, not as
    a scolding: the model is being asked to write the Chapter again, not to
    apologise for the last one."""
    lines = [
        "บทนี้ผิดกติกา Source note เขียนใหม่ทั้งบท:",
        *(f"- {problem}" for problem in verdict.problems),
        "",
        "กติกา: ข้อความที่มี Source note พูดเป็นข้อเท็จจริงได้ "
        "ข้อความที่ไม่มี ต้องพูดแบบเล่าต่อกันมา และห้ามมีตัวเลขหรือปีเลย",
    ]
    return "\n".join(lines)
