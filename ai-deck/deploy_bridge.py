"""Document-side bridge to a separately provisioned trusted deploy runner."""
import json
import base64
import os
from pathlib import Path
import re
import ssl
import socket
import http.client
import urllib.error
import urllib.parse
import urllib.request

ROUTE = re.compile(r'/deploy/(?:profiles|jobs(?:/[a-f0-9]{32})?)\Z')
USER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')
LIMIT = 256 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UnixHTTPSConnection(http.client.HTTPSConnection):
    """TLS keeps verifying the configured URL hostname over an SSH-forwarded socket."""
    def __init__(self, host, socket_path, **kwargs):
        super().__init__(host, **kwargs)
        self.socket_path = socket_path

    def connect(self):
        transport = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        transport.settimeout(self.timeout)
        try:
            transport.connect(self.socket_path)
            self.sock = self._context.wrap_socket(transport, server_hostname=self.host)
        except Exception:
            transport.close()
            raise


class RunnerHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, context, socket_path):
        super().__init__(context=context)
        self.socket_path = socket_path

    def https_open(self, request):
        def connection(host, **kwargs):
            return UnixHTTPSConnection(host, self.socket_path, **kwargs)
        return self.do_open(connection, request, context=self._context)


def handle(handler):
    if not handler.path.startswith('/deploy/'):
        return False
    if os.environ.get('CODE_WORKER') == '1' or not ROUTE.fullmatch(handler.path):
        handler._reply(404, 'Not found')
        return True
    owner = handler.headers.get('X-Desk-User', '')
    if not USER.fullmatch(owner):
        handler._reply(401, 'Authentication required')
        return True
    base = os.environ.get('AI_DECK_DEPLOY_URL', '').rstrip('/')
    token_file = os.environ.get('AI_DECK_DEPLOY_TOKEN_FILE', '')
    try:
        parsed = urllib.parse.urlsplit(base)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError('Runner URL must be an origin')
        token = Path(token_file).read_text().strip() if token_file else os.environ.get('AI_DECK_DEPLOY_TOKEN', '')
        if not token or '\n' in token or '\r' in token:
            raise ValueError('Runner credential unavailable')
    except (OSError, ValueError):
        handler._reply(503, 'Deployment runner is not configured')
        return True
    body = None
    if handler.command == 'POST':
        if handler.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            handler._reply(415, 'Use application/json')
            return True
        if handler.path != '/deploy/jobs':
            handler._reply(405, 'Method not allowed')
            return True
        data = handler._body(4096)
        if data is None:
            return True
        if set(data) != {'profile', 'sha'} or not isinstance(data['profile'], str) or not isinstance(data['sha'], str):
            handler._reply(400, 'Expected deployment profile and commit SHA')
            return True
        body = json.dumps(data).encode()
    request = urllib.request.Request(base + handler.path, data=body, method=handler.command, headers={
        'Authorization': 'Bearer ' + token, 'X-Desk-User': owner, 'Content-Type': 'application/json',
    })
    try:
        context = ssl.create_default_context()
        certificate = os.environ.get('AI_DECK_DEPLOY_CA_B64', '')
        if certificate:
            context.load_verify_locations(cadata=base64.b64decode(certificate, validate=True).decode('ascii'))
        socket_path = os.environ.get('AI_DECK_DEPLOY_SOCKET', '')
        transport = RunnerHTTPSHandler(context, socket_path) if socket_path else urllib.request.HTTPSHandler(context=context)
        if socket_path and parsed.scheme != 'https':
            raise ValueError('Socket transport requires HTTPS')
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), transport).open(request, timeout=10) as response:
            raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError('Runner response too large')
            # Re-serialize JSON, never pass arbitrary upstream HTML to the UI.
            handler._json_body(json.dumps(json.loads(raw)))
    except urllib.error.HTTPError as exc:
        # The runner owns detailed sanitized errors; transport credentials never appear.
        message = {400: 'Invalid profile or commit SHA', 401: 'Runner authentication failed',
                   403: 'Deployment profile is not allowed for your account',
                   404: 'Deployment profile or job not found', 409: 'Deployment request conflicts with current state'}.get(exc.code, 'Deployment runner request failed')
        handler._reply(exc.code if exc.code in (400, 401, 403, 404, 409) else 502, message)
        exc.close()
    except (OSError, ValueError, urllib.error.URLError):
        handler._reply(502, 'Could not reach deployment runner')
    return True
