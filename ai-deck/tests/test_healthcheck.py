"""The container healthcheck covers every process, not just PID 1."""
import io
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

import healthcheck

ROOT = Path(__file__).resolve().parents[1]


def test_targets_cover_upload_chat_and_every_desk():
    checks = dict(healthcheck.targets({"DESK_USERS": "fixhardez:7681,Pookzii:7684"}))
    assert checks["upload.py"] == "http://127.0.0.1:7682/api/health"
    assert checks["chat.py"] == "http://127.0.0.1:7683/chat/health"
    assert checks["ttyd:7681"] == "http://127.0.0.1:7681/"
    assert checks["ttyd:7684"] == "http://127.0.0.1:7684/"


def test_no_roster_still_checks_the_default_desk():
    assert ("ttyd:7681", "http://127.0.0.1:7681/") in healthcheck.targets({})


def test_a_down_or_erroring_process_is_reported_by_name():
    class Fine(io.BytesIO):
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(url, timeout):
        if "7683" in url:
            raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
        if "7684" in url:
            raise urllib.error.HTTPError(url, 502, "bad", {}, None)
        return Fine(b"")

    bad = healthcheck.failures(healthcheck.targets({"DESK_USERS": "a:7681,b:7684"}), opener)
    assert len(bad) == 2
    assert bad[0].startswith("chat.py ")
    assert bad[1] == "ttyd:7684 HTTP 502"


def test_against_a_real_listener():
    class Ok(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers()
        def log_message(self, *a): pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Ok)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        assert healthcheck.failures([("x", "http://127.0.0.1:%d/" % port)]) == []
        assert healthcheck.failures([("y", "http://127.0.0.1:1/")])
    finally:
        server.shutdown()


def test_compose_wires_healthchecks_and_waits_for_the_desk():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]
    for name in ("ai-deck", "ai-deck-code"):
        assert services[name]["healthcheck"]["test"] == [
            "CMD", "python3", "/opt/ai-deck/healthcheck.py"]
    assert "wget" in " ".join(services["nginx"]["healthcheck"]["test"])
    assert services["nginx"]["depends_on"]["ai-deck"]["condition"] == "service_healthy"


def test_the_image_ships_the_healthcheck():
    assert "healthcheck.py" in (ROOT / "Dockerfile").read_text()


def test_upload_health_answers_before_any_provider_or_workspace_lookup():
    source = (ROOT / "upload.py").read_text()
    body = source.split("    def do_GET(self):", 1)[1]
    assert body.index('"/api/health"') < body.index("self._provider()")
