"""Split Chapter prose into pieces small enough for one `synthesize` call.

The `synthesize` endpoint caps a request at 5,000 bytes and there is no setting
that raises it (docs/adr/0012). Thai costs three bytes a character, so a ~700
word Chapter is around 8,400 bytes and always needs two or three calls.

Cuts are made at sentence boundaries, never at a raw byte offset. A byte offset
lands mid-word, and Thai does not put spaces between words, so it lands mid-word
with no way to notice. The chunk boundaries themselves carry no meaning: nothing
downstream is keyed to them, they are never shown, and the audio is joined back
into one continuous Chapter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Thai writes no full stop. A space in Thai prose IS the sentence/clause break,
# so it is the primary cut point, alongside the Latin terminators that appear in
# quoted names and numbers, and the Thai abbreviation mark.
_SENTENCE_END = re.compile(r"(?<=[.!?ฯ])\s+|\n+|(?<=\S)[ \t]+")


@dataclass(frozen=True)
class Chunk:
    """One `synthesize` request's worth of text."""

    text: str
    #: True when no sentence boundary existed and the text had to be cut
    #: arbitrarily. Should never happen on real prose; if it does, the model
    #: emitted an unbroken run longer than the cap and the audio may clip a word.
    forced: bool = False

    @property
    def byte_length(self) -> int:
        return len(self.text.encode("utf-8"))


def _pieces(text: str) -> list[str]:
    """Break text into the smallest units a cut is allowed to fall between."""
    out: list[str] = []
    last = 0
    for match in _SENTENCE_END.finditer(text):
        piece = text[last : match.start()].strip()
        if piece:
            out.append(piece)
        last = match.end()
    tail = text[last:].strip()
    if tail:
        out.append(tail)
    return out


def _force_split(piece: str, limit: int) -> list[str]:
    """Cut an over-long unbreakable run. Last resort, and it is lossy in the
    sense that it may fall inside a Thai word — which is why callers surface
    `forced` rather than swallowing it."""
    out: list[str] = []
    current = ""
    for char in piece:
        candidate = current + char
        if len(candidate.encode("utf-8")) > limit:
            out.append(current)
            current = char
        else:
            current = candidate
    if current:
        out.append(current)
    return out


def split(text: str, limit: int) -> list[Chunk]:
    """Split `text` into chunks of at most `limit` bytes each.

    Pieces are packed greedily so the call count stays near the minimum: fewer
    calls means fewer prosody resets, which is the cost this design accepts
    (docs/adr/0012).
    """
    if limit <= 0:
        raise ValueError("limit must be positive")

    chunks: list[Chunk] = []
    current = ""

    def flush(forced: bool = False) -> None:
        nonlocal current
        if current:
            chunks.append(Chunk(current, forced))
            current = ""

    for piece in _pieces(text):
        if len(piece.encode("utf-8")) > limit:
            flush()
            for part in _force_split(piece, limit):
                chunks.append(Chunk(part, forced=True))
            continue

        candidate = f"{current} {piece}" if current else piece
        if len(candidate.encode("utf-8")) > limit:
            flush()
            current = piece
        else:
            current = candidate

    flush()
    return chunks
