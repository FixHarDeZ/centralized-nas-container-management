"""HTTP adapter for the optional coding worker; no agent or deployment access."""
import json
import os
import threading
from urllib.parse import parse_qs, urlparse

_stores = {}
_lock = threading.Lock()


def store():
    # Lazy import keeps the document worker independent of workspace setup.
    from workspaces import WorkspaceStore
    root = os.environ.get('WORKSPACE_ROOT', '/workspaces')
    with _lock:
        if root not in _stores:
            _stores[root] = WorkspaceStore(root)
        return _stores[root]


def enabled():
    return os.environ.get('CODE_WORKER') == '1'


def workspace(handler):
    from workspaces import WorkspaceError
    owner = handler.headers.get('X-Desk-User', '')
    if not owner:
        raise WorkspaceError('Authentication required', 401)
    wanted = parse_qs(urlparse(handler.path).query).get('workspace', [''])[0]
    if not wanted:
        raise WorkspaceError('Choose a coding workspace first', 400)
    return store().get(owner, wanted)


def handle(handler):
    """Return true when this adapter handled a /projects request."""
    path = urlparse(handler.path).path
    if not path.startswith('/projects'):
        return False
    if not enabled():
        handler._reply(404, 'Coding workspaces are not enabled')
        return True
    from workspaces import WorkspaceError
    try:
        owner = handler.headers.get('X-Desk-User', '')
        if not owner:
            handler._reply(401, 'Authentication required')
            return True
        if path == '/projects' and handler.command == 'GET':
            result = {'items': store().list(owner)}
        elif path == '/projects' and handler.command == 'POST':
            if handler.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                handler._reply(415, 'Use application/json')
                return True
            body = handler._body(4096)
            if body is None:
                return True
            if set(body) - {'url', 'branch'}:
                handler._reply(400, 'Expected a GitHub URL and optional base branch')
                return True
            result = store().create(owner, body.get('url', ''), body.get('branch', ''))
        elif path == '/projects/status' and handler.command == 'GET':
            item = workspace(handler)
            result = store().status(owner, item['id'])
        else:
            handler._reply(404, 'Not found')
            return True
        handler._json_body(json.dumps(result, ensure_ascii=False))
    except WorkspaceError as exc:
        handler._reply(exc.status, exc.message)
    except OSError:
        handler._reply(503, 'Workspace storage is unavailable')
    return True
