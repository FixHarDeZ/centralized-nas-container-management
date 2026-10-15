# shorts-factory/tests/test_studio_characters.py
import json

import pytest

from app import characters


@pytest.fixture(autouse=True)
def dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    return tmp_path


def nong(**extra):
    return {"id": "nong", "tag": "@Nong", "thai": "ผู้หญิงไทย 28 ปี ผมบ๊อบ แว่นกลม",
            "english": "", "flow_ready": False, **extra}


def test_missing_file_means_empty_library_and_hook_rule():
    assert characters.stored()["characters"] == []
    assert characters.default_for("th") == ""
    assert characters.default_sources(4) == ["flow", "pexels", "pexels", "pexels"]


def test_save_round_trips_and_defaults_per_channel(dirs):
    saved = characters.save({"characters": [nong()],
                             "defaults": {"th": "nong", "en": "", "shop": "nong"},
                             "footage": "all"})
    assert saved["defaults"]["th"] == "nong"
    assert characters.get("nong")["tag"] == "@Nong"
    assert characters.default_for("shop") == "nong"
    assert characters.default_sources(3) == ["flow", "flow", "flow"]
    assert json.loads((dirs / "config" / "characters.json").read_text())["footage"] == "all"


@pytest.mark.parametrize("bad", [
    {"characters": [nong(tag="Nong")]},                       # tag needs @
    {"characters": [nong(id="Has Space")]},                   # id slug
    {"characters": [nong(), nong()]},                         # duplicate id
    {"characters": [nong(thai="")]},                          # thai required
    {"characters": [nong(english="ผู้หญิง")]},                 # english must be latin
    {"characters": [nong()], "defaults": {"th": "ghost"}},    # unknown default
    {"characters": [], "footage": "sometimes"},               # unknown rule
])
def test_invalid_payload_writes_nothing(dirs, bad):
    with pytest.raises(ValueError):
        characters.save(bad)
    assert not (dirs / "config" / "characters.json").exists()


def test_unknown_default_on_disk_falls_back_to_none(dirs):
    (dirs / "config" / "characters.json").write_text(json.dumps(
        {"characters": [], "defaults": {"th": "gone"}, "footage": "hook"}))
    assert characters.default_for("th") == ""


def test_english_cache_is_keyed_by_the_thai_text(dirs):
    c = nong()
    assert characters.cached_english(c) == ""
    characters.remember_english(c, "the same 28-year-old Thai woman")
    assert characters.cached_english(c) == "the same 28-year-old Thai woman"
    assert characters.cached_english(nong(thai="ผู้ชายไทย")) == ""
    assert characters.cached_english(nong(english="typed by hand")) == "typed by hand"


def test_from_form_reads_rows_and_drops_blank_ones():
    form = {"char_0_id": "nong", "char_0_tag": "@Nong", "char_0_thai": "ผู้หญิง",
            "char_0_english": "", "char_0_ready": "on",
            "char_1_id": "", "char_1_tag": "", "char_1_thai": "",
            "default_th": "nong", "default_en": "", "default_shop": "", "footage": "hook"}
    payload = characters.from_form(form)
    assert payload["characters"] == [{"id": "nong", "tag": "@Nong", "thai": "ผู้หญิง",
                                      "english": "", "flow_ready": True}]
    assert payload["defaults"] == {"th": "nong", "en": "", "shop": ""}


@pytest.mark.parametrize("field", ["tag", "thai"])
def test_a_filled_row_with_a_blank_id_is_an_error(field):
    form = {"char_0_id": "", "char_0_tag": "", "char_0_thai": "", "char_0_english": "",
            "default_th": "", "default_en": "", "default_shop": "", "footage": "hook"}
    form[f"char_0_{field}"] = "@Mek" if field == "tag" else "ผู้ชาย"
    with pytest.raises(ValueError, match="ต้องใส่ id"):
        characters.validate(characters.from_form(form))


def test_a_fully_blank_row_is_still_a_blank_slot():
    form = {"char_0_id": " ", "char_0_tag": "", "char_0_thai": "", "char_0_english": "",
            "default_th": "", "default_en": "", "default_shop": "", "footage": "hook"}
    assert characters.validate(characters.from_form(form))["characters"] == []
