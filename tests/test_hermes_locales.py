"""Guards for the Hermes i18n overlay (hermes-agent/locales/), copied to $HERMES_HOME/locales/ by sync.sh.

The overlay is a PARTIAL catalog over Hermes' bundled locales/en.yaml: a key Hermes renames on an upgrade is
silently ignored and the English line comes back. The bundled check runs where the bundled catalog exists
(the sync gate inside hermes-gateway) and is skipped on the workstation.
"""
import os
import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "hermes-agent" / "locales" / "en.yaml"
BUNDLED = pathlib.Path(os.environ.get("HERMES_BUNDLED_LOCALES", "/opt/hermes/locales")) / "en.yaml"
CJK = re.compile(r"[　-鿿가-힯＀-￯]")   # mimo slips Chinese into Thai lines
QUEUED = "📥 รับคิวแล้วค่ะ"                                       # Fix 2026-11-26: "ตอบ รับคิวแล้ว"


def flat(node, prefix=""):
    out = {}
    for k, v in node.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        out.update(flat(v, key) if isinstance(v, dict) else {key: v})
    return out


def overlay():
    return flat(yaml.safe_load(OVERLAY.read_text(encoding="utf-8")))


def test_overlay_is_the_thai_busy_ack_only():
    cat = overlay()
    assert cat and all(k.startswith("gateway.busy.") for k in cat)
    assert cat["gateway.busy.ack_detail_wrap"] == ""          # no English "(iteration 4/250, running: terminal)"
    for k, v in cat.items():
        assert isinstance(v, str) and not CJK.search(v), k
        assert "{" not in v and "}" not in v, k                # heads/tails take no format fields
        if k.endswith("_head"):
            assert v.startswith(QUEUED), k
        if k.endswith("_tail"):
            assert v.startswith(" — ") and "ค่ะ" in v, k


def test_every_mode_reads_as_queued():
    cat = overlay()
    for mode in ("interrupting", "redirected", "queued", "steered", "steered_subagents"):
        assert f"gateway.busy.{mode}_head" in cat and f"gateway.busy.{mode}_tail" in cat, mode
    for head in ("compressing_head", "subagent_working_head"):
        assert f"gateway.busy.{head}" in cat
    assert "gateway.busy.demoted_tail" in cat


@pytest.mark.skipif(not BUNDLED.is_file(), reason="bundled Hermes locales only exist inside hermes-gateway")
def test_overlay_keys_exist_in_the_bundled_catalog():
    bundled = flat(yaml.safe_load(BUNDLED.read_text(encoding="utf-8")))
    missing = sorted(set(overlay()) - set(bundled))
    assert not missing, f"Hermes renamed these keys; the English line is back: {missing}"
    assert bundled["gateway.busy.ack"] == "{head}{detail}{tail}"


def test_sync_copies_the_overlay():
    sync = (ROOT / "hermes-agent" / "skills" / "sync.sh").read_text(encoding="utf-8")
    assert "hermes-agent/locales/*.yaml" in sync and "tests/test_hermes_locales.py" in sync
