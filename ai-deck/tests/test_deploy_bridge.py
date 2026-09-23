import io
import json
import deploy_bridge


class Handler:
    path = '/deploy/profiles'
    command = 'GET'
    headers = {'X-Desk-User': 'alice'}
    result = None

    def _reply(self, code, message):
        self.result = (code, message)

    def _json_body(self, body):
        self.result = (200, json.loads(body))


def test_bridge_disabled_without_config(monkeypatch):
    monkeypatch.delenv('AI_DECK_DEPLOY_URL', raising=False)
    h = Handler()
    assert deploy_bridge.handle(h)
    assert h.result[0] == 503


def test_coding_worker_cannot_use_bridge(monkeypatch):
    monkeypatch.setenv('CODE_WORKER', '1')
    h = Handler()
    assert deploy_bridge.handle(h)
    assert h.result[0] == 404


def test_bridge_rejects_unknown_routes_before_network(monkeypatch):
    h = Handler()
    h.path = '/deploy/jobs/../../credentials'
    assert deploy_bridge.handle(h)
    assert h.result[0] == 404


def test_bridge_forwards_only_authenticated_identity_and_fixed_credentials(tmp_path, monkeypatch):
    token = tmp_path / 'token'
    token.write_text('runner-secret')
    monkeypatch.setenv('AI_DECK_DEPLOY_URL', 'http://127.0.0.1:8768')
    monkeypatch.setenv('AI_DECK_DEPLOY_TOKEN_FILE', str(token))
    captured = []

    class Response(io.BytesIO):
        status = 200

    class Opener:
        def open(self, request, timeout):
            captured.append(request)
            return Response(b'{"items": []}')

    monkeypatch.setattr(deploy_bridge.urllib.request, 'build_opener', lambda *a: Opener())
    h = Handler()
    assert deploy_bridge.handle(h)
    assert h.result == (200, {'items': []})
    assert captured[0].get_header('Authorization') == 'Bearer runner-secret'
    assert captured[0].get_header('X-desk-user') == 'alice'


def test_unix_transport_preserves_tls_hostname(monkeypatch):
    seen = []
    class Socket:
        def settimeout(self, value): pass
        def connect(self, path): seen.append(('path', path))
        def close(self): pass
    class Context:
        def wrap_socket(self, sock, server_hostname):
            seen.append(('hostname', server_hostname))
            return sock
    monkeypatch.setattr(deploy_bridge.socket, 'socket', lambda *a: Socket())
    connection = deploy_bridge.UnixHTTPSConnection('runner.example:8792', '/work/.runner/runner.sock')
    connection._context = Context()
    connection.connect()
    assert seen == [('path', '/work/.runner/runner.sock'), ('hostname', 'runner.example')]
