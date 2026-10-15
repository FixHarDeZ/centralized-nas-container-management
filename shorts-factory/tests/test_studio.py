import json
import os
import subprocess
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
    with pytest.raises(ValueError):
        studio.root("20261015-170226-065-../x")


def test_a_bumped_clip_id_gets_a_pack_folder():
    assert studio.root("20261015-170226-065-1").name == "20261015-170226-065-1"


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


def make_testsrc(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size=720x1280:rate=24:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=duration={seconds}", "-shortest",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(path)],
                   check=True, capture_output=True)
    return path


def has_audio(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                          "stream=index", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return bool(out.stdout.strip())


def test_cut_gives_each_card_its_shots_silently(dirs):
    export = make_testsrc(dirs / "export.mp4", 24)
    assert studio.duration(export) == pytest.approx(24.0, abs=0.05)
    made = studio.cut(export, [0, 2], {0: 1, 2: 2}, "20261015-170226-065", 8.0)
    assert set(made) == {0, 2}
    assert studio.duration(made[0]) == pytest.approx(8.0, abs=0.1)
    assert studio.duration(made[2]) == pytest.approx(16.0, abs=0.1)
    assert not has_audio(made[0])


def test_cut_evenly_splits_the_real_length(dirs):
    export = make_testsrc(dirs / "short.mp4", 21)
    shot = studio.shot_length(studio.duration(export), 3, even=True)
    made = studio.cut(export, [1], {1: 3}, "20261015-170226-065", shot)
    assert studio.duration(made[1]) == pytest.approx(21.0, abs=0.1)


def test_saved_narration_is_dropped_when_say_changes(dirs, monkeypatch):
    from app import render
    monkeypatch.setattr(render, "SAY_PATH", dirs / "data" / "say.json")
    where = studio.root("20261015-170226-065")
    where.mkdir(parents=True)
    audio = where / "take.wav"
    audio.write_bytes(b"RIFF")
    (where / "narration.json").write_text(json.dumps(
        {"audio": str(audio), "starts": [0.0, 7.0], "total": 15.0, "spans": [7.0, 8.2],
         "say": studio.say_digest()}))
    assert studio.load_narration("20261015-170226-065") == (audio, [0.0, 7.0])
    render.SAY_PATH.write_text('{"พาส": "พาสะ"}', encoding="utf-8")
    assert studio.load_narration("20261015-170226-065") is None


def test_a_restart_puts_back_an_export_caught_mid_cut(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_INBOX", str(tmp_path / "inbox"))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "aaaaaaaaaaaa.mp4.taken").write_bytes(b"x")
    (inbox / "bbbbbbbbbbbb.mp4.taken").write_bytes(b"x")
    assert studio.unclaim_inbox({"aaaaaaaaaaaa"}) == 1
    assert (inbox / "aaaaaaaaaaaa.mp4").is_file()
    assert (inbox / "bbbbbbbbbbbb.mp4.taken").is_file()


def test_studio_clips_are_left_out_of_the_tally():
    from app import experiment
    arm = sorted(experiment.VARIANTS)[0]
    plain = {"variant": arm, "outcome": "rendered", "render": {"cards": [{"footage_source": "flow"}]}}
    flow = {"variant": arm, "outcome": "rendered",
            "render": {"cards": [{"footage_source": "flow-studio"}, {"footage_source": "pexels"}]}}
    assert experiment.studio_clip(flow) and not experiment.studio_clip(plain)
    assert experiment.tally([plain, flow])[arm]["clips"] == 1
