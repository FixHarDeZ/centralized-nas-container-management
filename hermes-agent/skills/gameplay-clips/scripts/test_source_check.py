"""Unit tests for source_check.verdict (no network)."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("source_check", os.path.join(HERE, "source_check.py"))
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)


def meta(title, channel, desc=""):
    return {"title": title, "channel": channel, "description": desc, "webpage_url": "u", "duration": 60}


def test_model_tokens_ignore_spacing_and_case():
    v = sc.verdict(meta("VITURE Pro2 XR Glasses | Official Film", "VITURE"), ["Pro 2 XR"], "viture")
    assert v["ok"] and v["official"] and v["missing_tokens"] == []


def test_wrong_model_fails():
    v = sc.verdict(meta("VITURE Pro XR Glasses launch", "VITURE"), ["Pro 2 XR"], "VITURE")
    assert not v["ok"] and v["missing_tokens"] == ["Pro 2 XR"]


def test_third_party_upload_is_not_official():
    v = sc.verdict(meta("VITURE Pro 2 XR review!!", "TechGuy Reviews"), ["Pro 2 XR"], "VITURE")
    assert not v["ok"] and not v["official"] and v["missing_tokens"] == []


def test_model_in_description_counts():
    v = sc.verdict(meta("New washer film", "Samsung Thailand", "Bespoke AI WW12DB8B95GB"), ["WW12DB8B95"], "samsung")
    assert v["ok"]


def test_thai_tokens():
    v = sc.verdict(meta("เครื่องซักผ้า ฝาหน้า 12 กก.", "LG Thailand"), ["12 กก"], "LG")
    assert v["ok"]
