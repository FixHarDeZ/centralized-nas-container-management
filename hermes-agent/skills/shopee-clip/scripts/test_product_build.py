"""Unit tests for product_build.py pure helpers. Run with pytest."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("product_build", os.path.join(HERE, "product_build.py"))
pb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pb)


def test_fit_holds_short_footage_and_flags_long_holds():
    total, hold, flags = pb.fit(18.0, 17.0, 1.6)
    assert total == 18.6 and hold == 0.6 and flags == []
    _, hold, flags = pb.fit(12.0, 17.0, 1.6)
    assert hold == 6.6 and "shorter" in flags[0]
    _, hold, flags = pb.fit(30.0, 17.0, 1.6)
    assert hold == 0 and "past the VO" in flags[0]


def test_pill_rules():
    ok = [{"text": "Soft Tip", "start": 0.4, "end": 2.0}, {"text": "Link below!", "start": 16, "end": 18}]
    assert pb.check_pills(ok, 18.6) == []
    bad = [{"text": "Super Soft Tip", "start": 0, "end": 2}, {"text": "50% off", "start": 1, "end": 3},
           {"text": "ดีมาก", "start": 5, "end": 25}]
    text = " ".join(pb.check_pills(bad, 18.6))
    for needle in ("<=2 words", "money", "overlap", "outside"):
        assert needle in text, needle


def test_set_marginv_only_touches_style():
    ass = ("[V4+ Styles]\nStyle: Sub,Itim,48,&H0066D1FF,&H0066D1FF,&H00203050,&H60203050,1,0,0,0,100,100,0,0,1,5,2.5,2,50,50,290,1\n"
           "Dialogue: 0,0:00:00.10,0:00:01.00,Sub,,0,0,0,,สวัสดี\n")
    out = pb.set_marginv(ass, 465)
    assert ",50,50,465,1" in out and "สวัสดี" in out
