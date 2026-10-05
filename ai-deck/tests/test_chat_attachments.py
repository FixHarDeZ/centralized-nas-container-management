"""Real HTTP uploads and sends, without invoking an account's agent."""
import io
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pytest
import chat
from workspaces import WorkspaceError


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('CODE_WORKER', '1')
    monkeypatch.setenv('WORKSPACE_ROOT', str(tmp_path))
    ident = 'a' * 32
    worktree = tmp_path / 'worktrees' / 'alice' / ident
    worktree.mkdir(parents=True)
    def workspace(handler):
        from urllib.parse import urlparse, parse_qs
        owner = handler.headers.get('X-Desk-User')
        if not owner:
            raise WorkspaceError('Authentication required', 401)
        wanted = parse_qs(urlparse(handler.path).query).get('workspace', [''])[0]
        if not wanted:
            raise WorkspaceError('Choose a coding workspace first', 400)
        if owner != 'alice' or wanted != ident:
            raise WorkspaceError('Workspace not found', 404)
        return {'id': ident, 'path': str(worktree)}
    monkeypatch.setattr(chat.workspace_api, 'workspace', workspace)
    class Agent:
        cwd = str(worktree)
        model = effort = ''
        calls = []
        def send(self, text, **kwargs):
            self.calls.append(text)
            return 200, 'ok'
    agent = Agent()
    monkeypatch.setattr(chat, 'agent_for', lambda *args: agent)
    monkeypatch.setattr(chat.agent_options, 'validate', lambda *args: True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), chat.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    def request(path, data=b'', method='PUT', owner='alice', workspace=ident, headers=None):
        head = {'X-Desk-User': owner} if owner else {}
        head.update(headers or {})
        req = urllib.request.Request(
            f'http://127.0.0.1:{server.server_port}{path}?workspace={workspace}',
            data=data, method=method, headers=head)
        try:
            response = urllib.request.urlopen(req, timeout=3)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, response.read().decode()
    yield request, agent, tmp_path
    server.shutdown()
    server.server_close()


def upload(api, name='รูป.png', data=b'fake image'):
    code, body = api[0]('/chat/attachments/' + quote(name, safe=''), data)
    assert code == 200, body
    return json.loads(body)


def test_upload_and_send_local_paths_outside_git(api):
    one = upload(api)
    two = upload(api, data=b'other image')
    assert one['id'] != two['id']
    assert one['name'] == 'รูป.png' and one['size'] == 10
    paths = list((api[2] / 'attachments').rglob('รูป.png'))
    assert len(paths) == 2 and {p.read_bytes() for p in paths} == {b'fake image', b'other image'}
    assert not list((api[2] / 'worktrees').rglob('รูป.png'))
    code, body = api[0]('/chat/send', json.dumps({'text': 'Explain this', 'attachments': [one['id']]}).encode(), 'POST')
    assert code == 200, body
    assert 'Explain this' in api[1].calls[0]
    assert any(str(p) in api[1].calls[0] for p in paths)


def test_attachment_only_turn(api):
    item = upload(api, 'notes.txt', b'notes')
    code, body = api[0]('/chat/send', json.dumps({'text': '', 'attachments': [item['id']]}).encode(), 'POST')
    assert code == 200, body
    assert 'notes.txt' in api[1].calls[0]


@pytest.mark.parametrize('name', ['../escape', 'a/b', 'a\\b', '.env', 'bad\nname', 'x' * 201])
def test_reject_bad_filenames(api, name):
    code, _ = api[0]('/chat/attachments/' + quote(name, safe=''), b'x')
    assert code == 400


@pytest.mark.parametrize('owner,workspace,expected', [('', 'a'*32, 401), ('bob', 'a'*32, 404), ('alice', '', 400), ('alice', 'b'*32, 404)])
def test_upload_requires_owned_workspace(api, owner, workspace, expected):
    code, _ = api[0]('/chat/attachments/file.txt', b'x', owner=owner, workspace=workspace)
    assert code == expected
    assert not (api[2] / 'attachments').exists()


@pytest.mark.parametrize('refs', [['../escape'], ['b'*32 + '/x'], 'x', [1], ['b'*32 + '/x'] * 11])
def test_send_rejects_invalid_or_missing_references(api, refs):
    code, _ = api[0]('/chat/send', json.dumps({'text': 'Read', 'attachments': refs}).encode(), 'POST')
    assert code in (400, 404)
    assert not api[1].calls


def test_reject_symlink_storage(api, tmp_path):
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (api[2] / 'attachments').symlink_to(elsewhere, target_is_directory=True)
    code, _ = api[0]('/chat/attachments/file.txt', b'x')
    assert code == 400
    assert not list(elsewhere.iterdir())


def test_reject_symlink_reference(api):
    item = upload(api, 'file.txt', b'x')
    path = next((api[2] / 'attachments').rglob('file.txt'))
    path.unlink()
    path.symlink_to('/etc/hosts')
    code, _ = api[0]('/chat/send', json.dumps({'text': 'Read', 'attachments': [item['id']]}).encode(), 'POST')
    assert code == 400
    assert not api[1].calls


def test_upload_size_limit(api):
    code, _ = api[0]('/chat/attachments/file.txt', b'', headers={'Content-Length': str(20*1024*1024+1)})
    assert code == 413


def test_documents_do_not_accept_coding_attachments(api, monkeypatch):
    monkeypatch.delenv('CODE_WORKER')
    code, _ = api[0]('/chat/attachments/file.txt', b'x')
    assert code == 404
    code, _ = api[0]('/chat/send', json.dumps({'text': 'Read', 'attachments': ['a'*32 + '/x']}).encode(), 'POST')
    assert code == 400
    assert not api[1].calls


def test_incomplete_upload_is_removed(api):
    import chat_attachments
    class Connection:
        def settimeout(self, value):
            pass
    class Handler:
        path = '/chat/attachments/partial.txt?workspace=' + 'a'*32
        headers = {'X-Desk-User': 'alice', 'Content-Length': '10'}
        rfile = io.BytesIO(b'cut')
        connection = Connection()
    with pytest.raises(WorkspaceError, match='Incomplete upload'):
        chat_attachments.receive(Handler())
    assert not list((api[2] / 'attachments').rglob('partial.txt'))
    assert not list((api[2] / 'attachments').rglob('.upload'))


def test_existing_file_cannot_be_referenced_from_another_owned_workspace(api, monkeypatch):
    item = upload(api, 'private.txt')
    monkeypatch.setattr(chat.workspace_api, 'workspace', lambda handler: {
        'id': 'b'*32, 'path': str(api[2] / 'other-worktree')})
    code, _ = api[0]('/chat/send', json.dumps({'text': 'Read', 'attachments': [item['id']]}).encode(), 'POST')
    assert code == 404
    assert not api[1].calls


def test_existing_file_cannot_be_referenced_by_another_owner(api, monkeypatch):
    item = upload(api, 'private.txt')
    monkeypatch.setattr(chat.workspace_api, 'workspace', lambda handler: {
        'id': 'a'*32, 'path': str(api[2] / 'bob-worktree')})
    code, _ = api[0]('/chat/send', json.dumps({'text': 'Read', 'attachments': [item['id']]}).encode(), 'POST', owner='bob')
    assert code == 404
    assert not api[1].calls


def test_nested_directory_symlink_is_rejected(api):
    item = upload(api, 'private.txt')
    directory = next((api[2] / 'attachments').rglob('private.txt')).parent
    (directory / 'private.txt').unlink()
    directory.rmdir()
    directory.symlink_to('/etc', target_is_directory=True)
    code, _ = api[0]('/chat/send', json.dumps({'text': 'Read', 'attachments': [item['id']]}).encode(), 'POST')
    assert code == 400
    assert not api[1].calls


def test_text_only_still_sends_unchanged(api):
    code, _ = api[0]('/chat/send', b'{"text":"hello"}', 'POST')
    assert code == 200
    assert api[1].calls == ['hello']


def test_coding_upload_is_packaged_and_bypasses_static_file_regex():
    root = Path(__file__).resolve().parents[1]
    assert 'chat_attachments.py' in (root / 'Dockerfile').read_text()
    config = (root / 'nginx/nginx.conf').read_text()
    block = config.split('location ^~ /code/chat/ {')[1].split('}')[0]
    assert 'client_max_body_size 20m;' in block
    assert 'proxy_set_header X-Desk-User $remote_user;' in block
    assert 'proxy_request_buffering off;' in block


def test_extension_header_is_put_back(api):
    code, body = api[0]('/chat/attachments/' + quote('รูป', safe=''), b'img',
                        headers={'X-Upload-Ext': '.png'})
    assert code == 200, body
    item = json.loads(body)
    assert item['name'] == 'รูป.png' and item['id'].endswith('/รูป.png')
    assert [p.read_bytes() for p in (api[2] / 'attachments').rglob('รูป.png')] == [b'img']
    code, body = api[0]('/chat/send', json.dumps({'text': '', 'attachments': [item['id']]}).encode(), 'POST')
    assert code == 200, body
    assert 'รูป.png' in api[1].calls[0]


@pytest.mark.parametrize('ext', ['png', '.a/b', '.%2Fx', '.tar.gz', '..', '.%0Ax', '.', '.abcdefghijklmnop'])
def test_bad_extension_header_is_rejected(api, ext):
    code, _ = api[0]('/chat/attachments/photo', b'img', headers={'X-Upload-Ext': ext})
    assert code == 400
    assert not list((api[2] / 'attachments').rglob('photo*'))


def test_double_encoded_extension_stays_literal(api):
    code, body = api[0]('/chat/attachments/photo', b'img', headers={'X-Upload-Ext': '.%252F'})
    assert code == 200, body
    assert json.loads(body)['name'] == 'photo.%2F'
