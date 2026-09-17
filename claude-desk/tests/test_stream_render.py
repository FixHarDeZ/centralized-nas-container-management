"""How an answer fills in, checked in a real browser.

`ui/stream.js` is the one piece of the page whose correctness is about what
the DOM did, not about what it ended up looking like — so it is tested by
running `tests/stream_harness.html` in headless Chrome and reading back the
counters it leaves in the page.

The rule being defended: while text is arriving, nothing already on screen is
rebuilt. The first chat view re-ran the markdown pass over the whole answer for
every token, which throws away and recreates every node of the reply. A test
that only looked at the final DOM would have passed on that.

Chrome is a workstation tool, not a container one — the suite skips when it is
not installed rather than pretending the check ran.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent / "stream_harness.html"

CHROMES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
    "chromium-browser",
)


def find_chrome():
    for candidate in CHROMES:
        if candidate.startswith("/"):
            if Path(candidate).exists():
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    return None


@pytest.fixture(scope="module")
def result():
    chrome = find_chrome()
    if not chrome:
        pytest.skip("no Chrome/Chromium to run the harness in")
    proc = subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            # The harness ends on its own; virtual time runs the rAF chain at
            # full speed and stops the browser once it goes idle.
            "--virtual-time-budget=20000",
            "--dump-dom",
            HARNESS.as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    match = re.search(r'<pre id="result">(.*?)</pre>', proc.stdout, re.S)
    assert match, f"harness produced no result\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    payload = match.group(1).strip()
    assert payload != "pending", "harness never finished streaming"
    return json.loads(payload)


def test_markdown_runs_once_and_only_when_the_text_ends(result):
    # This is the assertion the old implementation failed: it parsed and
    # rebuilt the whole answer on every delta.
    assert result["rendersDuringStream"] == 0
    assert result["renders"] == 1


def test_completed_paragraphs_are_never_touched_again(result):
    assert result["firstParaStillThere"] is True
    # One text node per paragraph while streaming, which is what makes a delta
    # cost one `appendData` instead of a rebuild.
    assert result["streamNodes"] == result["paragraphs"]


def test_deltas_are_coalesced_into_frames(result):
    # Deltas arrive in bursts between frames; each burst must cost one commit,
    # not one per delta.
    assert result["commits"] < result["deltas"]
    assert result["commits"] <= (result["deltas"] // result["burst"]) + 2


def test_layout_is_not_read_per_delta(result):
    # Whether the reader is at the bottom comes from an IntersectionObserver.
    # The only `scrollHeight` read left is the scroll itself, once per commit.
    assert result["scrollReads"] <= result["commits"] + 2


def test_the_answer_survives_all_of_that(result):
    assert result["textOk"] is True
