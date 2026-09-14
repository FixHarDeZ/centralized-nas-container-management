"""Chapter timestamps, measured rather than predicted.

shorts-factory has machinery that reconciles edge-tts's reported
`SentenceBoundary` offsets against the file, because that endpoint returns one
blob plus offsets that overstate the real positions. None of it transfers here:
Google's `synthesize` returns N separate files, so there are no offsets to
distrust. A Chapter starts at the running sum of the measured durations of the
trimmed chunks before it.

The pause tags Chirp 3: HD accepts in its `markup` field are deliberately not
used to compute anything — they are non-deterministic, so a timestamp derived
from one would drift against the audio.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Marker:
    """One published timestamp in the video description."""

    title: str
    start: float

    def label(self) -> str:
        """`MM:SS Title`, or `H:MM:SS Title` past the hour. YouTube needs the
        first marker to be 00:00 for chapters to appear at all."""
        total = int(self.start)
        hours, rest = divmod(total, 3600)
        minutes, seconds = divmod(rest, 60)
        stamp = (
            f"{hours}:{minutes:02d}:{seconds:02d}"
            if hours
            else f"{minutes:02d}:{seconds:02d}"
        )
        return f"{stamp} {self.title}"


def markers(titles: list[str], durations: list[float]) -> list[Marker]:
    """Chapter titles plus their measured audio durations, in order, into the
    timestamps that go in the description."""
    if len(titles) != len(durations):
        raise ValueError(
            f"{len(titles)} chapter titles against {len(durations)} durations",
        )

    out: list[Marker] = []
    elapsed = 0.0
    for title, duration in zip(titles, durations):
        out.append(Marker(title, elapsed))
        elapsed += duration
    return out


def description_block(markers_: list[Marker]) -> str:
    return "\n".join(m.label() for m in markers_)
