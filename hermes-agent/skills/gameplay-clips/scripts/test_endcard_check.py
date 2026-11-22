"""endcard_check.cut_boxes: text touching the frame edge = a cut title (no OCR run here)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from endcard_check import cut_boxes  # noqa: E402


def box(x0, x1):
    return [[x0, 300], [x1, 300], [x1, 340], [x0, 340]]


def test_title_at_the_edge_is_cut_and_a_whole_card_is_not():
    hits = cut_boxes([(box(10, 717), "IPER ELITE", 0.9), (box(1, 63), "SWITCH.", 0.8)], 720, 24.6)
    assert [(h["text"], h["side"]) for h in hits] == [("IPER ELITE", "right"), ("SWITCH.", "left")]
    # gotg-encore-gp: a whole 16:9 card whose small print ends 5 px from the edge
    assert cut_boxes([(box(521, 715), "INCLUDES EXCLUSIVE OUTFITS", 0.9)], 720, 22.3) == []
    # low confidence / 1-2 characters are noise
    assert cut_boxes([(box(0, 30), "IP", 0.9), (box(0, 300), "SNIPER", 0.3)], 720, 1.0) == []
