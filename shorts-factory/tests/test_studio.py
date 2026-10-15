import os
import time

import pytest

from app import studio


@pytest.fixture(autouse=True)
def dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("STUDIO_INBOX", str(tmp_path / "inbox"))
    return tmp_path


@pytest.mark.parametrize("span, shots", [(7.4, 1), (7.5, 1), (7.6, 2), (13.3, 2), (15.6, 3), (0.0, 1)])
def test_shots_per_span(span, shots):
    assert studio.shots_for(span) == shots


def test_spans_pad_the_last_card():
    assert studio.spans([0.0, 7.0, 16.0], 24.0, 0.2) == [7.0, 9.0, pytest.approx(8.2)]


def test_pending_skips_pexels_and_cards_with_footage():
    assert studio.pending_cards(["flow", "pexels", "flow", "flow"], {2}) == [0, 3]


def test_shot_map_and_totals():
    shots = studio.shot_map([7.0, 9.0, 8.2], [0, 2])
    assert shots == {0: 1, 2: 2}
    assert studio.total_shots(shots) == 3
    assert studio.credits(3) == 36


def test_fits_within_half_a_second():
    assert studio.fits(24.0, 3) and studio.fits(23.6, 3) and studio.fits(24.5, 3)
    assert not studio.fits(21.0, 3)
    assert studio.shot_length(24.0, 3, even=False) == 8.0
    assert studio.shot_length(21.0, 3, even=True) == 7.0


def test_tokens_are_twelve_hex():
    token = studio.new_token()
    assert studio.TOKEN.fullmatch(token) and token != studio.new_token()


def test_pack_round_trip_and_discard():
    studio.write_pack("20261015-170226-065", {"token": "a" * 12}, "# Shot list")
    assert studio.read_pack("20261015-170226-065")["token"] == "a" * 12
    assert studio.read_markdown("20261015-170226-065") == "# Shot list"
    studio.discard("20261015-170226-065")
    assert studio.read_pack("20261015-170226-065") is None


def test_unsafe_clip_ids_are_refused():
    with pytest.raises(ValueError):
        studio.root("../etc")


def test_have_segments_lists_cards_with_files():
    path = studio.segment_path("20261015-170226-065", 2)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")
    assert studio.have_segments("20261015-170226-065", 4) == {2}


def test_claim_inbox_takes_only_live_tokens_once(dirs):
    inbox = dirs / "inbox"
    inbox.mkdir()
    (inbox / ("a" * 12 + ".mp4")).write_bytes(b"x")
    (inbox / ("b" * 12 + ".mp4")).write_bytes(b"x")
    (inbox / ("a" * 12 + ".mp4.part")).write_bytes(b"x")
    taken = studio.claim_inbox({"a" * 12})
    assert [t for t, _ in taken] == ["a" * 12]
    assert taken[0][1].name.endswith(".taken")
    assert studio.claim_inbox({"a" * 12}) == []


def test_sweep_removes_stale_and_unknown_old_files(dirs):
    inbox = dirs / "inbox"
    inbox.mkdir()
    old = inbox / ("c" * 12 + ".mp4")
    old.write_bytes(b"x")
    past = time.time() - 73 * 3600
    os.utime(old, (past, past))
    fresh = inbox / ("d" * 12 + ".mp4")
    fresh.write_bytes(b"x")
    assert studio.sweep_inbox(set()) == 1
    assert fresh.exists() and not old.exists()


def test_version_for_message():
    wait = {"kind": "studio", "versions": {"a" * 12: {"message_id": 5}, "b" * 12: {"message_id": 9}}}
    assert studio.version_for_message(wait, 9) == "b" * 12
    assert studio.version_for_message(wait, 4) is None
    assert studio.version_for_message({"message_id": 9}, 9) is None
