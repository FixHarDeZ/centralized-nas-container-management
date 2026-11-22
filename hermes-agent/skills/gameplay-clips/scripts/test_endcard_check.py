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


def test_text_at_the_end_card_pictures_top_or_bottom_is_cut():
    """switch2-oblivion-rd 2026-11-22: "OUT NOW" ended 1 px above the bottom of the card's picture (y 348-750)."""
    rect = [0, 348, 720, 750]
    def vbox(y0, y1, x0=270, x1=450):
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    hits = cut_boxes([(vbox(700, 749), "OUT NOW", 0.9), (vbox(350, 380), "The Elder", 0.9)], 720, 20.6, rect)
    assert [(h["text"], h["side"]) for h in hits] == [("OUT NOW", "bottom"), ("The Elder", "top")]
    # whole card: margins > 4 px; subtitle and pill outside the picture are not the card's
    assert cut_boxes([(vbox(690, 730), "OUT NOW", 0.9), (vbox(760, 800), "ลิงก์ใต้คลิป", 0.9),
                      (vbox(200, 240), "Link below!", 0.9)], 720, 20.6, rect) == []
    assert cut_boxes([(vbox(700, 749), "OUT NOW", 0.9)], 720, 20.6) == []          # no rect: old behaviour
