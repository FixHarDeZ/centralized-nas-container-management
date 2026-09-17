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


# ── The page's half of a reconnect ────────────────────────────────────────
# The rules being checked live in app.js, not stream.js: ignore an event
# already applied, and redraw the turn when the server says everything since
# the drop is gone. The page is driven in demo mode — no websocket, no stream,
# no agent — through the `window._chat` hook app.js exposes only there.

@pytest.fixture(scope="module")
def resync():
    import functools
    import http.server
    import socketserver
    import threading

    chrome = find_chrome()
    if not chrome:
        pytest.skip("no Chrome/Chromium to run the harness in")

    root = Path(__file__).resolve().parents[1]
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    # Over HTTP, not file://: the harness reaches into the page it frames, and
    # Chrome gives every file:// document its own opaque origin.
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    server.allow_reuse_address = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = "http://127.0.0.1:%d/tests/chat_resync_harness.html" % server.server_address[1]
    try:
        proc = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
             "--virtual-time-budget=20000", "--dump-dom", url],
            capture_output=True, text=True, timeout=120,
        )
    finally:
        server.shutdown()
        server.server_close()

    match = re.search(r'<pre id="result">(.*?)</pre>', proc.stdout, re.S)
    assert match, f"harness produced no result\n{proc.stdout[-2000:]}"
    payload = match.group(1).strip()
    assert payload != "pending", "harness never finished"
    data = json.loads(payload)
    assert "error" not in data, data
    return data


def test_an_event_already_applied_is_ignored(resync):
    # A replay and the live stream overlap by design: chat.py subscribes before
    # it replays, so every reconnect delivers some events twice.
    assert resync["seqFollowed"] is True
    assert resync["afterReplayBubbles"] == 1
    assert resync["textBeforeDrop"] == "หนึ่ง "
    assert resync["textAfterMore"].count("ซ้ำ") == 0


def test_a_snapshot_redraws_the_turn_it_came_back_to(resync):
    # One bubble, holding what the agent has said so far, and the tool that is
    # still running drawn as still running.
    assert resync["bubblesAfterResync"] == 1
    assert resync["textAfterResync"] == "หนึ่ง สอง สาม"
    assert resync["pillsAfterResync"] == 1
    assert resync["openPills"] == 1


def test_the_turn_carries_on_into_the_same_bubble(resync):
    assert resync["textAfterMore"] == "หนึ่ง สอง สาม สี่"
    assert resync["bubblesAtEnd"] == 1


def test_a_finished_tool_is_marked_not_just_coloured(resync):
    # Colour alone says nothing to a colour-blind reader, and little to anyone
    # holding a phone in sunlight, so a finished pill carries a mark.
    #
    # The order is the rule the page has always used: a result belongs to the
    # oldest pill still open. The snapshot's tool was the oldest, so it takes
    # the first result, and the one left running keeps its dot.
    assert resync["marks"] == ["✓", "✕", ""]
