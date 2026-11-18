"""Unit tests for windows.py's pure parts (span maths + OCR rules); no media, no models."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("windows", os.path.join(HERE, "windows.py"))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def hit(text, score=0.9):
    return [{"text": text, "score": score}]


def test_subtract_and_pad():
    assert w.subtract([(0, 10)], [(2, 3), (5, 6)]) == [(0, 2), (3, 5), (6, 10)]
    assert w.subtract([(0, 10)], [(-1, 1), (9, 12)]) == [(1, 9)]
    assert w.pad([(1, 2), (2.2, 3)], 0.15, 0, 10) == [(0.85, 3.15)]


def test_overlay_is_not_text_and_single_chars_are_suspect():
    ocr = {str(t): hit("WB GAMES") for t in range(8)}
    ocr["3"] = hit("WB GAMES") + hit("Every spell")
    ocr["5"] = hit("WB GAMES") + hit("C")
    skip = set(w.overlays(ocr))
    assert skip == {"WBGAMES"}
    assert w.classify(ocr["0"], skip) == ("clean", [])
    assert w.classify(ocr["3"], skip)[0] == "text"
    assert w.classify(ocr["5"], skip) == ("suspect", ["C"])
    assert w.classify(hit("Every spell", 0.3), skip) == ("clean", [])      # low confidence


def test_dirty_span_runs_to_the_neighbouring_clean_samples():
    ocr = {"10.0": [], "11.0": hit("Every story"), "12.0": hit("Every story"), "13.0": [],
           "10.75": [], "13.25": hit("Every story"), "13.5": []}
    # the 0.25 probes say text is still there at 13.25 but gone at 13.5 and absent at 10.75
    assert w.dirty_spans(ocr, set()) == [(10.75, 13.5)]


def test_refine_probes_only_the_run_edges():
    ocr = {"10.0": [], "11.0": hit("TEXT"), "12.0": hit("TEXT"), "13.0": []}
    assert w.refine_times(ocr, set(), 0, 100) == [10.25, 10.5, 10.75, 12.25, 12.5, 12.75]


def test_ocr_grid_covers_both_ends():
    assert w.ocr_grid([(22.3, 24.8)]) == [22.3, 23.3, 24.3, 24.8]


def test_frame_flags_dark_and_cuts():
    times = [i / w.FPS for i in range(12)]
    luma = [80] * 5 + [10, 12] + [80] * 5
    diff = [0, 2, 2, 2, 2, 40, 2, 45, 2, 2, 2, 2]
    dark, cuts, med = w.frame_flags(times, luma, diff)
    assert dark == [(1.125, 1.625)]
    assert cuts == [1.25, 1.75] and med == 2


def test_describe_flags_static_cards():
    times = [i / w.FPS for i in range(20)]
    still = w.describe(0.0, 4.0, times, [60] * 20, [0.3] * 20, [], {}, set())
    moving = w.describe(0.0, 4.0, times, [60] * 20, [9.0] * 20, [], {}, set())
    assert still["static"] and not moving["static"]
    assert still["score"] < moving["score"]
    assert moving["tiles"] == [0.2, 2.0, 3.8]
