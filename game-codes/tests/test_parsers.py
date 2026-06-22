from pathlib import Path

from game_code_notifier import (
    fetch_api_seria,
    fetch_table_status,
    fetch_section_regex,
)

FIX = Path(__file__).parent / "fixtures"


def _read(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_seria_keeps_only_ok_status():
    src = {"type": "api_seria"}
    codes = {e["code"] for e in fetch_api_seria(src, _read("genshin.json"))}
    assert codes == {"GENSHINGIFT"}


def test_wuwa_keeps_only_active_rows():
    src = {"code_regex": r"^[A-Z0-9]{4,20}$"}
    codes = {e["code"] for e in fetch_table_status(src, _read("wuwa.html"))}
    assert codes == {"WUTHERINGGIFT"}  # Expired row dropped


def test_wuwa_live_dom_status_in_button_label():
    # Live wuthering.gg renders status as a button label ("COPY" / "Expired")
    # plus tr class="active", not plain "Active"/"Expired" cell text.
    src = {"code_regex": r"^[A-Z0-9]{4,20}$"}
    codes = {e["code"] for e in fetch_table_status(src, _read("wuwa_live.html"))}
    assert codes == {"WUTHERINGGIFT"}
    assert "ILLUSIONHAUNTS" not in codes


def test_roe_scopes_to_section_and_ignores_decoys():
    src = {"scope_selector": ".entry-content", "code_regex": r"\b[A-Za-z0-9]{11}\b"}
    codes = {e["code"] for e in fetch_section_regex(src, _read("roe.html"))}
    assert codes == {"1gzUiopoEHg", "6D79Kt9M8XD"}
    assert "RANDOMWORD11" not in codes  # outside scope, not matched


def test_tod_regex_requires_digit():
    src = {"scope_selector": ".post-body", "code_regex": r"\btod(?=[a-z0-9]*\d)[a-z0-9]{3,}\b"}
    codes = {e["code"] for e in fetch_section_regex(src, _read("tod.html"))}
    assert codes == {"tod18347", "todhot666"}
    assert "todays" not in codes
