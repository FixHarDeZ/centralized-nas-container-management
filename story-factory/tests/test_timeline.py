from app.timeline import Marker, description_block, markers

import pytest


def test_the_first_chapter_starts_at_zero():
    # YouTube shows no chapters at all unless the first timestamp is 00:00.
    out = markers(["เปิดเรื่อง", "ฟันที่พบ"], [610.0, 480.0])
    assert out[0].start == 0.0
    assert out[0].label().startswith("00:00")


def test_each_chapter_starts_where_the_measured_audio_left_off():
    out = markers(["ก", "ข", "ค"], [60.0, 90.5, 30.0])
    assert [m.start for m in out] == [0.0, 60.0, 150.5]


def test_labels_gain_an_hour_field_past_the_hour():
    assert Marker("ตอนจบ", 3725.0).label() == "1:02:05 ตอนจบ"
    assert Marker("กลางเรื่อง", 605.0).label() == "10:05 กลางเรื่อง"


def test_mismatched_counts_are_an_error_not_a_silent_truncation():
    with pytest.raises(ValueError):
        markers(["ก", "ข"], [60.0])


def test_description_block_is_one_marker_per_line():
    block = description_block(markers(["ก", "ข"], [60.0, 60.0]))
    assert block == "00:00 ก\n01:00 ข"
