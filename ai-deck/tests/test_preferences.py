"""Account state and model selection without credentials or paid requests."""
import json
import subprocess
from types import SimpleNamespace

import pytest

import chat
import codex_backend
import upload
from .test_codex import api, events_until, fake_codex  # noqa: F401


@pytest.mark.parametrize('code,output,expected', [
    (0, 'Logged in using ChatGPT SECRET', 'signed_in'),
    (1, 'Not logged in', 'signed_out'),
    (1, 'Unexpected failure SECRET', 'unknown'),
])
def test_auth_status_is_redacted(monkeypatch, api, code, output, expected):
    def run(args, **kwargs):
        assert args == ['codex', 'login', 'status']
        assert kwargs['timeout'] <= 10
        return SimpleNamespace(returncode=code, stdout='', stderr=output)
    monkeypatch.setattr(subprocess, 'run', run)
    status, body = api(upload.Handler, 'GET', '/api/auth?provider=codex')
    assert status == 200
    assert json.loads(body) == {'status': expected}
    assert 'SECRET' not in body


def test_auth_timeout_is_unknown(monkeypatch, api):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired('codex', 5)
    monkeypatch.setattr(subprocess, 'run', run)
    status, body = api(upload.Handler, 'GET', '/api/auth?provider=codex')
    assert status == 200
    assert json.loads(body)['status'] == 'unknown'


def test_codex_selection_reaches_new_and_resumed_turn(fake_codex):
    agent = chat.CodexAgent(cwd=str(fake_codex))
    channel = agent.subscribe()
    for prompt in ['first', 'second']:
        assert agent.send(prompt, model='test-model', effort='high')[0] == 200
        events_until(channel, 'turn')
        args = json.loads((fake_codex / 'received.json').read_text())['args']
        assert args[args.index('--model') + 1] == 'test-model'
        assert 'model_reasoning_effort="high"' in args


def test_invalid_preferences_rejected_before_launch(api):
    for body in [{'text': 'hello', 'model': []},
                 {'text': 'hello', 'model': '--help'},
                 {'text': 'hello', 'effort': 'nonsense'},
                 {'text': 'hello', 'model': 'haiku', 'effort': 'high'}]:
        assert api(chat.Handler, 'POST', '/chat/send', body)[0] == 400


def test_claude_switch_resumes_and_busy_does_not_change_options(monkeypatch):
    agent = chat.Agent()
    agent.session_id = '0199a213-81c0-7800-8aa1-bbab2a035a53'
    agent.model, agent.effort = 'sonnet', 'low'
    calls = []
    monkeypatch.setattr(agent, 'running', lambda: True)
    monkeypatch.setattr(agent, 'stop_child', lambda: calls.append('stop'))
    monkeypatch.setattr(agent, 'start', lambda resume='': calls.append(resume))
    monkeypatch.setattr(agent, '_write', lambda payload: True)
    assert agent.send('next', model='opus', effort='high')[0] == 200
    assert calls == ['stop', agent.session_id]
    assert (agent.model, agent.effort) == ('opus', 'high')
    assert agent.send('busy', model='sonnet', effort='low')[0] == 409
    assert (agent.model, agent.effort) == ('opus', 'high')


def test_catalog_normalizes_capabilities_and_hides_internal_models(monkeypatch, api):
    import agent_options
    monkeypatch.setattr(agent_options, '_cached', (float('-inf'), []))
    monkeypatch.setattr(agent_options, '_installed_codex_models', lambda: [
        {'model': 'test-model', 'displayName': 'Test model',
         'supportedReasoningEfforts': [{'reasoningEffort': 'low'}, {'reasoningEffort': 'high'}]},
        {'model': 'internal-model', 'hidden': True},
    ])
    status, body = api(chat.Handler, 'GET', '/chat/options?provider=codex')
    assert status == 200
    assert json.loads(body)['models'] == [
        {'id': '', 'label': 'Default', 'efforts': []},
        {'id': 'test-model', 'label': 'Test model', 'efforts': ['low', 'high']},
    ]
    assert agent_options.validate('codex', 'test-model', 'high')
    assert not agent_options.validate('codex', 'test-model', 'max')
    assert not agent_options.validate('codex', 'internal-model', '')


def test_claude_process_arguments_preserve_resume(monkeypatch, tmp_path):
    import sys
    from .test_chat import FAKE_AGENT
    agent = chat.Agent(command=[sys.executable, '-u', '-c', FAKE_AGENT], cwd=str(tmp_path))
    channel = agent.subscribe()
    try:
        assert agent.send('first', model='sonnet', effort='low')[0] == 200
        events_until(channel, 'turn')
        sid = '0199a213-81c0-7800-8aa1-bbab2a035a53'
        agent.session_id = sid
        old_proc = agent.proc
        assert agent.send('second', model='opus', effort='high')[0] == 200
        events_until(channel, 'turn')
        assert old_proc.poll() is not None
        assert agent.proc.args[-6:] == ['--model', 'opus', '--effort', 'high', '--resume', sid]
    finally:
        with agent.lock:
            agent.stop_child()
