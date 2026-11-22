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


def test_grab_never_seeks_past_the_last_frame():
    assert w.grab_time(93.89, 93.89) == 93.79
    assert w.grab_time(10.0, 93.89) == 10.0
    assert w.grab_time(0.0, 0.05) == 0.0
    assert w.grab_time(12.5, None) == 12.5


def test_failed_grabs_are_dirty_never_an_overlay():
    failed = [{"text": w.GRAB_FAILED, "score": 1.0}]
    ocr_map = {str(float(t)): failed for t in range(8)}
    assert w.overlays(ocr_map) == []
    assert w.classify(failed, set(w.overlays(ocr_map)))[0] == "text"
    assert w.dirty_spans(ocr_map, set()) == [(-1.0, 8.0)]


def test_ocr_frames_survives_a_bad_grab(monkeypatch, tmp_path):
    monkeypatch.setattr(w, "grab", lambda src, t, out, dur=None: False)
    out = w.ocr_frames("x.mp4", [1.0, 2.0], lambda f: ([], None), str(tmp_path), dur=2.0)
    assert out == {"1.0": [{"text": w.GRAB_FAILED, "score": 1.0}], "2.0": [{"text": w.GRAB_FAILED, "score": 1.0}]}


def test_wash_spans_cut_the_white_flash_with_its_ramp():
    """switch2-oblivion-rd trailer, measured at 30 fps around 78.29 s and 81.59 s."""
    rate = 30.0
    means = [120.0] * 2400
    stds = [40.0] * 2400
    for t, m, sd in ((78.221, 231.9, 5.5), (78.254, 250.3, 1.4), (78.287, 255.0, 0.0), (78.321, 250.6, 1.0),
                     (78.354, 233.9, 3.9), (12.203, 229.9, 20.2)):           # last: bright WITH detail = kept
        i = int(round(t * rate))
        means[i], stds[i] = m, sd
    spans = w.wash_spans(means, stds, rate)
    assert len(spans) == 1
    a, b = spans[0]
    assert 78.0 < a < 78.21 and 78.37 < b < 78.5


def test_asr_extends_vad_tails_and_drops_far_hallucinations():
    vad = [(10.0, 12.0), (30.0, 31.0)]
    asr = [(10.5, 13.1),        # quiet tail under music: VAD stopped 1.1 s early -> extended
           (13.2, 14.0),        # within ASR_NEAR of the VAD span: same speech
           (50.0, 52.0)]        # no VAD near: "do do do" on music -> dropped
    assert w.asr_extend(vad, asr) == [(10.0, 13.1), (13.2, 14.0), (30.0, 31.0)]   # PAD joins the 0.1 s gap later
    assert w.asr_extend([], asr) == []


def test_write_vtt_rebases_to_master_time(tmp_path):
    p = w.write_vtt([(10.0, 14.0), (2.0, 3.0)], str(tmp_path / "s.vtt"), rebase=5.0)
    txt = open(p).read()
    assert txt.startswith("WEBVTT") and "00:00:05.000 --> 00:00:09.000" in txt and "00:00:02" not in txt
