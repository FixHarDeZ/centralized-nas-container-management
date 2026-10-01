"""HTTP adapter for the optional coding worker; no agent or deployment access."""
import json
import os
import tempfile
import threading
import uuid
from urllib.parse import parse_qs, urlparse

MAX_BUNDLE_BYTES = 300 * 1024 * 1024  # matches nginx client_max_body_size
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


def _query(handler, key):
    return parse_qs(urlparse(handler.path).query).get(key, [''])[0]


def _receive_bundle(handler, owner):
    """Stream a PUT body to incoming/<owner>/<uuid>.bundle; returns its path."""
    from workspaces import WorkspaceError
    handler.close_connection = True
    if handler.headers.get('Transfer-Encoding'):
        raise WorkspaceError('Content-Length required', 411)
    try:
        length = int(handler.headers.get('Content-Length', ''))
    except ValueError:
        raise WorkspaceError('Content-Length required', 411)
    if length < 0:
        raise WorkspaceError('Invalid body length', 400)
    if length > MAX_BUNDLE_BYTES:
        raise WorkspaceError('Maximum bundle size is 300 MiB', 413)
    owned = store()
    owned._valid_owner(owner)
    directory = owned.root / 'incoming' / owner
    owned._make_safe_directory(directory.parent)
    owned._make_safe_directory(directory)
    target = directory / (uuid.uuid4().hex + '.bundle')
    descriptor, temporary = tempfile.mkstemp(prefix='.', suffix='.part', dir=directory)
    try:
        handler.connection.settimeout(120)
        with os.fdopen(descriptor, 'wb') as output:
            remaining = length
            while remaining:
                chunk = handler.rfile.read(min(remaining, 1 << 20))
                if not chunk:
                    raise WorkspaceError('Incomplete upload; try again', 400)
                output.write(chunk)
                remaining -= len(chunk)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target


def _send_file(handler, path, name):
    size = os.path.getsize(path)
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/octet-stream')
    handler.send_header('Content-Length', str(size))
    handler.send_header(
        'Content-Disposition', 'attachment; filename="%s"' % name
    )
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    with open(path, 'rb') as source:
        while True:
            chunk = source.read(1 << 20)
            if not chunk:
                break
            handler.wfile.write(chunk)


def _bundle_route(handler, owner, path):
    """PUT /projects/bundle (import/update) and GET /projects/export."""
    from workspaces import WorkspaceError
    if path == '/projects/bundle' and handler.command == 'PUT':
        wanted = _query(handler, 'workspace')
        slug = _query(handler, 'slug')
        if not wanted and not slug:
            raise WorkspaceError('Give a project name or a workspace', 400)
        if wanted:
            item = workspace(handler)
            return 200, store().update_bundle(
                owner, item['id'], _receive_bundle(handler, owner))
        store()._valid_slug(slug)  # reject before reading the body
        return 201, store().import_bundle(
            owner, slug, _receive_bundle(handler, owner),
            branch=_query(handler, 'branch'), name=_query(handler, 'name'),
            email=_query(handler, 'email'),
        )
    if path == '/projects/export' and handler.command == 'GET':
        item = workspace(handler)
        exported, name = store().export_bundle(
            owner, item['id'], force=_query(handler, 'force') == '1')
        try:
            _send_file(handler, exported, name)
        finally:
            try:
                os.unlink(exported)
            except OSError:
                pass
        return None, None
    return 0, None


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
        status, result = _bundle_route(handler, owner, path)
        if status is None:
            return True
        if status:
            handler._json_body(json.dumps(result, ensure_ascii=False), status)
            return True
        if path == '/projects' and handler.command == 'GET':
            result = {'items': [dict(item, source=item.get('source', 'github'))
                                for item in store().list(owner)]}
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
        elif path == '/projects' and handler.command == 'DELETE':
            item = workspace(handler)
            force = parse_qs(urlparse(handler.path).query).get('force', [''])[0] == '1'
            result = store().delete(owner, item['id'], force=force)
        elif path == '/projects/repositories' and handler.command == 'GET':
            from workspaces import github_repositories
            result = github_repositories()
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
