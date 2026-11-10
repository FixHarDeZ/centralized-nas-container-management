"""Guards for the repo-owned Hermes skills (hermes-agent/skills/).

- the router stays small (rules hide in a big SKILL.md; the old one reached 109 KB and gates were skipped)
- every SKILL.md has the frontmatter Hermes reads (name matches the dir, description present)
- only the router claims clip orders; mode skills say they are not an entry point
- file names are unique across the skills and every referenced file exists somewhere in them
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "hermes-agent" / "skills"
SKILLS = ["shopee-clip", "flow-driver", "gameplay-clips"]
ROUTER_BUDGET = 15 * 1024


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path}: no frontmatter"
    return dict(re.findall(r"^(\w+): (.*)$", m.group(1), re.M))


def test_router_size_budget():
    size = (ROOT / "shopee-clip" / "SKILL.md").stat().st_size
    assert size <= ROUTER_BUDGET, f"shopee-clip/SKILL.md is {size} B > {ROUTER_BUDGET} B — move detail to references/"


def test_frontmatter_names():
    for s in SKILLS:
        fm = frontmatter(ROOT / s / "SKILL.md")
        assert fm.get("name") == s
        assert fm.get("description")


def test_only_router_is_an_entry_point():
    for s in ("flow-driver", "gameplay-clips"):
        assert "Not an entry point" in frontmatter(ROOT / s / "SKILL.md")["description"], s
    assert "EVERY Shopee clip order" in frontmatter(ROOT / "shopee-clip" / "SKILL.md")["description"]


def files():
    for s in SKILLS:
        for p in (ROOT / s).rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts and p.name != "SKILL.md":
                yield s, p


def test_file_names_unique_across_skills():
    seen = {}
    for s, p in files():
        if p.suffix in (".md", ".py", ".js", ".sh"):
            assert p.name not in seen, f"{p.name} in both {seen[p.name]} and {s}"
            seen[p.name] = s


def test_every_referenced_file_exists():
    names = {p.name for _, p in files()}
    ref = re.compile(r"(?:references|templates|scripts)/([A-Za-z0-9_.-]+\.(?:md|py|js|sh))")
    missing = []
    for s in SKILLS:
        for p in (ROOT / s).rglob("*.md"):
            for name in ref.findall(p.read_text(encoding="utf-8")):
                if name not in names:
                    missing.append(f"{p.relative_to(ROOT)} -> {name}")
    assert not missing, missing


def test_no_live_reference_to_retired_skill_paths():
    bad = []
    for _s, p in files():
        if p.suffix in (".py", ".sh", ".js") and "skills/flow-shopee-clips" in p.read_text(encoding="utf-8", errors="ignore"):
            bad.append(str(p.relative_to(ROOT)))
    assert not bad, bad


def test_old_question_menu_stays_retired():
    router = (ROOT / "shopee-clip" / "SKILL.md").read_text(encoding="utf-8")
    for old in ("hands มือล้วน", "skit สถานการณ์", "broll สินค้าล้วน หมุนช้า"):
        assert old not in router, old
    house = (ROOT / "shopee-clip" / "references" / "house-rules.md").read_text(encoding="utf-8")
    i = house.index("- **ASK FIRST")
    assert "SUPERSEDED" in house[max(0, i - 400):i], "the old one-call duration+style question must stay marked superseded"
