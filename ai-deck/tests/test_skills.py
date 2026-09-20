"""The vendored workstation skills, and the three places that must agree.

ai-deck/skills/ is a copy of skills that live on the workstation, so the
usual copy problem applies: the list, the copy, the mount and the link loop
can each drift on their own. What makes drift expensive here is that a skill
is only discovered by being a directory with a SKILL.md under
~/.claude/skills — a half-copied one fails silently, with the agent simply
never mentioning it.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
LIST = ROOT / "skills.list"

# Same markers scripts/desk_skills.py refuses on. Repeated rather than
# imported: this test also has to catch a file added to the copy by hand.
SECRET_MARKERS = (
    "auth_info",
    "credentials",
    "token.json",
    "cookies",
    ".env",
    "id_rsa",
    "id_ed25519",
    "keys.txt",
)


def listed() -> list:
    names = []
    for line in LIST.read_text(encoding="utf-8").splitlines():
        name = line.split("#", 1)[0].strip()
        if name:
            names.append(name)
    return names


def vendored() -> list:
    return sorted(d.name for d in SKILLS.iterdir() if d.is_dir())


def test_list_and_copy_hold_the_same_names():
    assert sorted(listed()) == vendored()


def test_every_vendored_skill_is_discoverable():
    """A directory without SKILL.md is invisible to the agent, not an error."""
    for name in vendored():
        assert (SKILLS / name / "SKILL.md").is_file(), f"{name} has no SKILL.md"


def test_no_credential_shaped_files_travel():
    for path in SKILLS.rglob("*"):
        if not path.is_file():
            continue
        rel = str(path.relative_to(SKILLS)).lower()
        assert not any(m in rel for m in SECRET_MARKERS), f"{rel} looks like a secret"


def test_image_bakes_the_copy_where_the_entrypoint_looks():
    """A ./skills bind would be 0700 to uid 1000 (DSM share ACL), so it is a
    COPY. The Dockerfile's destination and the entrypoint's source are the
    two halves of that, written in different files."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    copied = re.search(r"^COPY[^\n]*\sskills/\s+(\S+)", dockerfile, re.M)
    assert copied, "Dockerfile no longer COPYs skills/"
    dest = copied.group(1).rstrip("/")
    assert dest in entrypoint, f"entrypoint.sh does not link anything from {dest}"


def test_skills_are_not_bind_mounted():
    """The trap this stack has hit twice: a directory bind from
    /volume2/docker is unreadable to uid 1000 and chmod on the NAS does not
    stick, so the mount looks fine and the skills silently do not exist."""
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./skills:" not in compose
