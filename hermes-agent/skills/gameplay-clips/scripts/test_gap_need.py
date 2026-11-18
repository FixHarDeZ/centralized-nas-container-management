"""vo_gates.gap_need: the VO pause gate scales with VO length (4 per 20 s)."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("vo_gates", os.path.join(HERE, "vo_gates.py"))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def test_twenty_seconds_keeps_the_old_four():
    assert g.gap_need(20.97) == 4      # lego-hp-switch2-gameplay take


def test_ten_second_clip_of_four_phrases_can_pass():
    assert g.gap_need(8.22) == 2       # nikos-bath-toy: 3 gaps, the fixed 4 could never pass


def test_floor_is_one():
    assert g.gap_need(3.0) == 1
    assert g.gap_need(0.0) == 1


def test_longer_clip_asks_for_more():
    assert g.gap_need(30.0) == 6
