"""Workspace identity must follow every chat/history/resume route."""
import json
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

import chat
import upload


def test_agents_are_scoped_by_workspace_and_cwd(tmp_path):
    a = chat.agent_for('alice', 'claude', 'a', str(tmp_path / 'a'))
    b = chat.agent_for('alice', 'claude', 'b', str(tmp_path / 'b'))
    assert a is not b
    assert a.cwd == str(tmp_path / 'a')
    assert chat.agent_for('alice', 'claude', 'a', str(tmp_path / 'a')) is a
    assert chat.agent_for('bob', 'claude', 'a', str(tmp_path / 'a')) is not a


def test_transcripts_and_resume_reject_other_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, 'HOME', str(tmp_path))
    session = '11111111-1111-1111-1111-111111111111'
    left, right = str(tmp_path / 'left'), str(tmp_path / 'right')
    directory = chat.session_directory(left)
    from pathlib import Path
    Path(directory).mkdir(parents=True)
    Path(directory, session + '.jsonl').write_text(json.dumps({
        'type': 'user', 'message': {'content': 'Only the left workspace'}}) + '\n')
    assert chat.transcript(session, left)[0]['text'] == 'Only the left workspace'
    assert chat.transcript(session, right) == []
    assert chat.Agent(cwd=right).reset(resume=session)[0] == 404


def test_code_worker_requires_authorized_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('CODE_WORKER', '1')
    monkeypatch.setenv('WORKSPACE_ROOT', str(tmp_path))
    server = ThreadingHTTPServer(('127.0.0.1', 0), chat.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path, headers, expected in [
            ('/chat/state', {}, 401),
            ('/chat/state', {'X-Desk-User': 'alice'}, 400),
            ('/chat/state?workspace=' + 'a'*32, {'X-Desk-User': 'alice'}, 404),
        ]:
            req = urllib.request.Request('http://127.0.0.1:%s%s' % (server.server_port, path), headers=headers)
            try:
                urllib.request.urlopen(req, timeout=2)
                assert False, 'request should fail closed'
            except urllib.error.HTTPError as exc:
                assert exc.code == expected
    finally:
        server.shutdown()
        server.server_close()


def test_invalid_project_bodies_return_400(tmp_path, monkeypatch):
    monkeypatch.setenv('CODE_WORKER', '1')
    monkeypatch.setenv('WORKSPACE_ROOT', str(tmp_path))
    server = ThreadingHTTPServer(('127.0.0.1', 0), chat.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for body in ([], ['url'], None, {}, {'url': []}):
            req = urllib.request.Request('http://127.0.0.1:%s/projects' % server.server_port,
                data=json.dumps(body).encode(), headers={'X-Desk-User': 'alice', 'Content-Type': 'application/json'})
            try:
                urllib.request.urlopen(req, timeout=2)
                assert False, 'invalid body should fail'
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_terminals_are_distinct_per_owner_and_workspace(monkeypatch):
    import coding_terminal
    class Store:
        def get(self, owner, ident):
            return {'path': '/workspaces/' + owner + '/' + ident}
    monkeypatch.setattr(chat.workspace_api, 'store', lambda: Store())
    a, b = 'a'*32, 'b'*32
    first = coding_terminal.command('alice', a)
    second = coding_terminal.command('alice', b)
    assert first[first.index('-s') + 1] != second[second.index('-s') + 1]
    assert first[-1] == '/workspaces/alice/' + a
    assert second[-1] == '/workspaces/alice/' + b
    assert coding_terminal.session_name('alice', a) != coding_terminal.session_name('bob', a)
    import pytest
    with pytest.raises(ValueError):
        coding_terminal.command('alice', '../escape')


def test_terminal_starts_in_authorized_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('CODE_WORKER', '1')
    monkeypatch.setattr(chat.workspace_api, 'workspace', lambda h: {'id': 'a'*32, 'path': str(tmp_path / 'repo name')})
    calls = []
    monkeypatch.setattr(upload, 'type_into_pane', lambda command, target: calls.append(command) or (200, 'ok'))
    server = ThreadingHTTPServer(('127.0.0.1', 0), upload.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request('http://127.0.0.1:%s/api/new?provider=claude&workspace=%s' % (server.server_port, 'a'*32),
                                     data=b'', headers={'X-Desk-User': 'alice'}, method='POST')
        with urllib.request.urlopen(req, timeout=2) as response:
            assert response.status == 200
        import shlex
        assert calls == ['cd -- ' + shlex.quote(str(tmp_path / 'repo name')) + ' && claude']
    finally:
        server.shutdown()
        server.server_close()
