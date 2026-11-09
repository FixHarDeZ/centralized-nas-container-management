"""Presenter Shots workflow JSON must be generated from core.js (no hand edits in n8n)."""
import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEN = ROOT / "n8n" / "presenter-shots" / "build_workflow.py"
WF = ROOT / "n8n" / "workflows" / "Presenter_Shots.json"
CORE = ROOT / "n8n" / "presenter-shots" / "core.js"


def _gen():
    spec = importlib.util.spec_from_file_location("build_workflow", GEN)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_workflow_matches_generator():
    assert WF.read_text(encoding="utf-8") == _gen().render(), "run build_workflow.py"


def test_code_nodes_embed_core_verbatim():
    wf = json.loads(WF.read_text(encoding="utf-8"))
    core = CORE.read_text(encoding="utf-8")
    codes = {n["name"]: n["parameters"]["jsCode"] for n in wf["nodes"] if n["type"] == "n8n-nodes-base.code"}
    assert set(codes) == {"Apply event", "Find stalls"}
    for src in codes.values():
        assert core in src


def test_shape_auth_and_tick():
    wf = json.loads(WF.read_text(encoding="utf-8"))
    by = {n["name"]: n for n in wf["nodes"]}
    assert by["Shot Event"]["parameters"]["path"] == "presenter-shots"
    assert by["Shot Event"]["parameters"]["responseMode"] == "responseNode"
    assert "timingSafeEqual" in by["Apply event"]["parameters"]["jsCode"]
    assert "CLIP_INTAKE_TOKEN" in by["Apply event"]["parameters"]["jsCode"]
    tick = by["Find stalls"]["parameters"]["jsCode"]
    assert "sd.state =" not in tick, "the stall tick must stay read-only"
    assert by["Alert Fix"]["credentials"]["telegramApi"]["name"] == "Secretary Bot"
    assert wf["settings"]["errorWorkflow"]
