"""Guard: CLAUDE.md's stack table, the disk, and deploy.sh must agree.

If this fails against the real repo (run `python3 scripts/check_doc_drift.py`
directly, it is not wired into this suite against real files), it means one
of three things drifted: a CLAUDE.md table row points at a directory that no
longer exists, a stack directory has no CLAUDE.md row, or a stack directory
and `ALL_STACKS` in `scripts/deploy.sh` disagree about whether the stack is
deployed. `scripts/check_doc_drift.py` is the standalone entry point that
names the drift and cites where to fix it.

This test file exercises the module's functions against small literal
fixture strings defined here, not against the real repo files, so it stays
green while real drift is being fixed.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_doc_drift.py"

_spec = importlib.util.spec_from_file_location("check_doc_drift", MODULE_PATH)
check_doc_drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_doc_drift)

documented_stacks = check_doc_drift.documented_stacks
deploy_stacks = check_doc_drift.deploy_stacks
find_drift = check_doc_drift.find_drift
TABLE_HEADER = check_doc_drift.TABLE_HEADER

SEPARATOR = "| :--- | :--- | :--- | :--- |"


def make_claude_md(rows: list[str]) -> str:
    """Build a fake CLAUDE.md around a table with the given row lines."""
    return "\n".join(
        [
            "# CLAUDE.md",
            "",
            "## Stacks",
            "",
            TABLE_HEADER,
            SEPARATOR,
            *rows,
            "",
            "## Next section",
        ]
    )


def test_documented_stacks_parses_normal_row():
    text = make_claude_md(["| `news-feed/` | Feed bot | 5064 / — | notes |"])
    result = documented_stacks(text)
    assert result == {"news-feed": 7}


def test_documented_stacks_tolerates_no_space_before_pipe():
    # Mirrors the real `| `uptime-kuma/`| ... |` spacing quirk.
    text = make_claude_md(["| `uptime-kuma/`| Service Monitor | 3001 / — | x |"])
    result = documented_stacks(text)
    assert result == {"uptime-kuma": 7}


def test_documented_stacks_stops_at_first_non_row_line():
    text = make_claude_md(
        [
            "| `news-feed/` | Feed bot | 5064 / — | notes |",
            "",
            "| `ghost-after-blank/` | should not be seen | — / — | x |",
        ]
    )
    result = documented_stacks(text)
    assert result == {"news-feed": 7}
    assert "ghost-after-blank" not in result


def test_deploy_stacks_parses_single_line_array():
    text = "ALL_STACKS=(secretary n8n news-feed claude-desk)\n"
    assert deploy_stacks(text) == {"secretary", "n8n", "news-feed", "claude-desk"}


def test_deploy_stacks_parses_wrapped_array():
    text = "ALL_STACKS=(\n  secretary\n  n8n\n  news-feed\n)\n"
    assert deploy_stacks(text) == {"secretary", "n8n", "news-feed"}


def test_find_drift_ghost_row():
    # Documented but not on disk.
    findings = find_drift(
        disk_stacks=set(),
        documented={"auth": 33},
        deployed=set(),
        deploy_sh_line=125,
    )
    assert len(findings) == 1
    assert "Ghost row" in findings[0]
    assert "auth" in findings[0]
    assert "CLAUDE.md:33" in findings[0]


def test_find_drift_undocumented_stack():
    # On disk but no table row.
    findings = find_drift(
        disk_stacks={"news-feed"},
        documented={},
        deployed={"news-feed"},
        deploy_sh_line=125,
    )
    assert len(findings) == 1
    assert "Undocumented stack" in findings[0]
    assert "news-feed" in findings[0]


def test_find_drift_deploy_list_missing_stack():
    # Stack directory exists and is documented, but ALL_STACKS omits it.
    findings = find_drift(
        disk_stacks={"story-factory"},
        documented={"story-factory": 40},
        deployed=set(),
        deploy_sh_line=125,
    )
    assert len(findings) == 1
    assert "Deploy-list mismatch" in findings[0]
    assert "story-factory" in findings[0]
    assert "scripts/deploy.sh:125" in findings[0]


def test_find_drift_deploy_list_extra_name():
    # ALL_STACKS names a stack with no matching directory.
    findings = find_drift(
        disk_stacks=set(),
        documented={},
        deployed={"phantom-stack"},
        deploy_sh_line=125,
    )
    assert len(findings) == 1
    assert "Deploy-list mismatch" in findings[0]
    assert "phantom-stack" in findings[0]
    assert "scripts/deploy.sh:125" in findings[0]


def test_find_drift_clean_case_yields_no_findings():
    disk = {"news-feed", "claude-desk"}
    documented = {"news-feed": 33, "claude-desk": 34}
    deployed = {"news-feed", "claude-desk"}
    assert documented == {"news-feed": 33, "claude-desk": 34}
    assert find_drift(disk, documented, deployed, deploy_sh_line=125) == []


stale_deploy_claims = check_doc_drift.stale_deploy_claims


def test_stale_deploy_claim_fires_when_row_prose_contradicts_array():
    text = make_claude_md(
        ["| `story-factory/` | Bot | — / — | **ยังไม่ deploy** ไม่อยู่ใน `ALL_STACKS` |"]
    )
    findings = stale_deploy_claims(text, {"story-factory"}, deploy_sh_line=125)
    assert len(findings) == 1
    assert "story-factory" in findings[0]
    assert "CLAUDE.md:7" in findings[0]


def test_stale_deploy_claim_silent_when_claim_is_true():
    text = make_claude_md(["| `story-factory/` | Bot | — / — | ไม่อยู่ใน `ALL_STACKS` |"])
    assert stale_deploy_claims(text, set(), deploy_sh_line=125) == []


def test_stale_deploy_claim_ignores_rows_not_mentioning_the_array():
    text = make_claude_md(["| `news-feed/` | Feed bot | 5064 / — | notes |"])
    assert stale_deploy_claims(text, {"news-feed"}, deploy_sh_line=125) == []


def test_stale_deploy_claim_ignores_a_row_that_corrects_itself():
    # The fix for a stale claim still names the array; it must not re-fire.
    text = make_claude_md(
        ["| `story-factory/` | Bot | — / — | อยู่ใน `ALL_STACKS` แล้วตั้งแต่ 15/09 |"]
    )
    assert stale_deploy_claims(text, {"story-factory"}, deploy_sh_line=125) == []


def test_the_real_repo_has_no_doc_drift():
    """The point of the whole file: real CLAUDE.md vs real disk vs real deploy.sh.

    Fails when a stack is added/removed without updating the CLAUDE.md table or
    `ALL_STACKS`. Run `python3 scripts/check_doc_drift.py` for the same report
    with exit codes.
    """
    claude_md_text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    deploy_sh_text = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    deploy_sh_line = check_doc_drift.deploy_stacks_line(deploy_sh_text)
    deployed = deploy_stacks(deploy_sh_text)

    findings = check_doc_drift.find_drift(
        check_doc_drift.stack_dirs(ROOT),
        documented_stacks(claude_md_text),
        deployed,
        deploy_sh_line,
    ) + stale_deploy_claims(claude_md_text, deployed, deploy_sh_line)

    assert findings == [], "\n".join(findings)
