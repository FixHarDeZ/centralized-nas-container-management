import pytest

from app import topics


def test_a_cryptid_subject_passes():
    topics.check("เมกะโลดอนยังมีชีวิตอยู่หรือไม่", stories_published=0, gate_until=10)


def test_a_religious_subject_is_blocked_early():
    with pytest.raises(topics.Blocked):
        topics.check("ตำนานนรกภูมิในพระไตรปิฎก", stories_published=3, gate_until=10)


def test_the_gate_opens_after_enough_stories():
    topics.check("ตำนานนรกภูมิ", stories_published=10, gate_until=10)


def test_a_leading_bang_overrides_the_gate():
    topics.check("!ตำนานนรกภูมิ", stories_published=0, gate_until=10)


def test_blocking_raises_rather_than_returning_a_flag():
    # A boolean can be ignored by a caller that forgot to check it, and the
    # result is a published video. Raising cannot be ignored.
    with pytest.raises(topics.Blocked) as excinfo:
        topics.check("ปาฏิหาริย์ที่วัด", stories_published=0, gate_until=10)
    assert "0011" in str(excinfo.value)


def test_the_override_marker_is_not_part_of_the_subject():
    assert topics.strip_override("!ตำนานนรกภูมิ") == "ตำนานนรกภูมิ"
    assert topics.strip_override("เมกะโลดอน") == "เมกะโลดอน"
