"""The checkpoint: what a Story in progress has already paid for.

A Story is seven model calls of a minute to five each, plus about twenty speech
requests, plus a 25-minute encode. Any of those can fail — mimo has sick
windows measured in shorts-factory — and without a record, a failure at Chapter
six throws away five Chapters of prose and the speech already bought for them.

So every Chapter is written here the moment it exists, and again when it has
been voiced. A Job that was not finished is offered back on the next start and
via `/resume`; the Chapters it already holds are never asked of the model
again, and the ones already voiced are never voiced again.

The workdir is the record. `story.json` inside it is the index; the `.wav`
files beside it are the paid-for parts. Nothing here is deleted on failure;
`prune()` keeps the last few finished ones for listening back (the raw speech
chunks in `raw/` are the evidence for docs/adr/0012's reversal condition).
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config, sources

INDEX = "story.json"


@dataclass
class Done:
    """One Chapter that exists. `duration` is None until it has been voiced."""

    title: str
    passages: list[dict]
    duration: float | None = None

    @property
    def prose(self) -> str:
        return "\n\n".join(p["text"] for p in self.passages)

    def as_passages(self) -> list[sources.Passage]:
        return [sources.Passage(p["text"], p.get("source", "")) for p in self.passages]


@dataclass
class Job:
    subject: str
    titles: list[str]
    workdir: Path
    chapters: list[Done] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    #: "" while in flight, then "finished" or "abandoned".
    outcome: str = ""
    output: str = ""

    # --- shape --------------------------------------------------------------

    @property
    def next_index(self) -> int:
        return len(self.chapters)

    @property
    def complete(self) -> bool:
        return self.next_index == len(self.titles)

    def audio(self, index: int) -> Path:
        return self.workdir / f"{index:02d}.wav"

    def scratch(self, index: int) -> Path:
        return self.workdir / "raw" / f"{index:02d}"

    def voiced(self, index: int) -> bool:
        """Voiced means the file is there, not that the index says so — a kill
        between the write and the save leaves the two disagreeing."""
        done = self.chapters[index]
        return done.duration is not None and self.audio(index).exists()

    # --- persistence --------------------------------------------------------

    def save(self) -> None:
        self.workdir.mkdir(parents=True, exist_ok=True)
        record = asdict(self)
        record["workdir"] = str(self.workdir)
        tmp = self.workdir / f"{INDEX}.tmp"
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1))
        tmp.replace(self.workdir / INDEX)

    @classmethod
    def load(cls, workdir: Path) -> "Job":
        record = json.loads((workdir / INDEX).read_text())
        record["workdir"] = workdir
        record["chapters"] = [Done(**c) for c in record.get("chapters", [])]
        return cls(**record)


def root() -> Path:
    return config.data_dir() / "work"


def new(subject: str, titles: list[str]) -> Job:
    job = Job(subject=subject, titles=titles, workdir=root() / str(int(time.time())))
    job.save()
    return job


def unfinished() -> Job | None:
    """The most recent Job that neither finished nor was given up on."""
    if not root().exists():
        return None
    for workdir in sorted(root().iterdir(), reverse=True):
        if not (workdir / INDEX).exists():
            continue
        job = Job.load(workdir)
        if not job.outcome:
            return job
    return None


def prune(keep: int | None = None) -> int:
    """Delete finished workdirs beyond the newest `keep`. In-flight and
    abandoned ones are left alone: in-flight is resumable, abandoned is a
    human's decision to inspect or delete by hand."""
    keep = config.keep_workdirs() if keep is None else keep
    if not root().exists():
        return 0
    finished = []
    for workdir in sorted(root().iterdir(), reverse=True):
        if (workdir / INDEX).exists() and Job.load(workdir).outcome == "finished":
            finished.append(workdir)
    removed = 0
    for workdir in finished[keep:]:
        shutil.rmtree(workdir, ignore_errors=True)
        removed += 1
    return removed
