"""One desk per person, and the two copies of the roster that must agree.

ttyd's --max-clients is per instance, so a single ttyd meant the second
person to open the page was refused the websocket and the page sat in its
reconnect loop forever. The fix is one ttyd (and one tmux session) per basic
auth user, which puts the roster in three places: docker-compose.yml starts
them, nginx routes to them, and upload.py has to drive the right one.
"""
import re
from pathlib import Path

import upload

ROOT = Path(__file__).resolve().parents[1]


def compose_roster() -> list:
    """[(user, port)] as docker-compose.yml declares it."""
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    spec = re.search(r"DESK_USERS=(\S+)", text).group(1)
    return [
        (entry.split(":")[0], int(entry.split(":")[1])) for entry in spec.split(",")
    ]


def nginx_map() -> tuple:
    """({user: port}, default port) as nginx.conf routes it."""
    text = (ROOT / "nginx/nginx.conf").read_text(encoding="utf-8")
    block = re.search(r"map \$remote_user \$desk_port \{(.*?)\}", text, re.S).group(1)
    routes, default = {}, None
    for line in block.strip().splitlines():
        key, value = line.strip().rstrip(";").split()
        if key == "default":
            default = int(value)
        else:
            routes[key] = int(value)
    return routes, default


def test_nginx_routes_every_desk_the_entrypoint_starts():
    """A user nginx sends to a port with no ttyd on it gets a 502, not a desk."""
    roster = compose_roster()
    routes, default = nginx_map()
    ports = {port for _user, port in roster}
    assert default == roster[0][1], "the default must be the desk ttyd runs as PID 1"
    for user, port in roster[1:]:
        assert routes.get(user) == port, f"nginx sends {user} somewhere else"
    assert set(routes.values()) <= ports


def test_every_desk_port_is_exposed():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for _user, port in compose_roster():
        assert re.search(rf'^\s+- "{port}"', text, re.M), f"port {port} is not exposed"


# ── upload.py picks the caller's session ──────────────────────────────────
def test_the_roster_names_sessions_the_way_the_entrypoint_does():
    """entrypoint.sh lowercases and replaces anything but [a-z0-9_-]."""
    assert upload.roster("fixhardez:7681,Pookzii:7684") == {
        "fixhardez": "fixhardez:0.0",
        "pookzii": "pookzii:0.0",
    }
    assert upload.roster("fix.hardez:7681") == {"fix.hardez": "fix-hardez:0.0"}


def test_each_user_drives_their_own_session(monkeypatch):
    """Otherwise one person's Quit lands in the other person's running turn."""
    monkeypatch.setattr(upload, "DESKS", upload.roster("a:7681,b:7684"))
    assert upload.target_for("a") == "a:0.0"
    assert upload.target_for("B") == "b:0.0"


def test_an_unlisted_user_lands_on_the_first_desk(monkeypatch):
    """A basic auth account that predates the roster still gets a terminal."""
    monkeypatch.setattr(upload, "DESKS", upload.roster("a:7681,b:7684"))
    assert upload.target_for("someone-else") == "a:0.0"
    assert upload.target_for("") == "a:0.0"


def test_without_a_roster_nothing_changes(monkeypatch):
    """Running upload.py outside the container still drives `main`."""
    monkeypatch.setattr(upload, "DESKS", {})
    assert upload.target_for("whoever") == upload.TMUX_TARGET
