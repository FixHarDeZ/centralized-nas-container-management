"""Quota is provider-specific and updated by web chat, not just terminal hooks."""
import json
import os
import time

import chat
import upload
from .test_codex import api  # noqa: F401


def test_claude_chat_rate_event_updates_api_without_terminal(tmp_path, monkeypatch, api):
    import usage_status
    path = tmp_path / 'chat-usage.json'
    monkeypatch.setattr(usage_status, 'CLAUDE_CHAT_FILE', path)
    monkeypatch.setattr(upload, 'STATUS_FILE', str(tmp_path / 'terminal.json'))
    monkeypatch.setattr(upload, 'DONE_FILE', str(tmp_path / 'done.json'))
    agent = chat.Agent()
    agent._translate({'type': 'rate_limit_event', 'rate_limit_info': {
        'status': 'allowed', 'rateLimitType': 'five_hour', 'utilization': .27,
        'resetsAt': time.time() + 3600}})
    status, body = api(upload.Handler, 'GET', '/api/status?provider=claude')
    assert status == 200
    data = json.loads(body)
    assert data['five_hour']['pct'] == 27
    assert data['five_hour']['age'] < 5
    assert data['provider'] == 'claude'


def test_partial_chat_update_does_not_refresh_old_week(tmp_path, monkeypatch):
    import usage_status
    monkeypatch.setattr(usage_status, 'CLAUDE_CHAT_FILE', tmp_path / 'chat.json')
    old = time.time() - 90000
    usage_status.CLAUDE_CHAT_FILE.write_text(json.dumps({'seven_day': {
        'pct': 70, 'resets_at': old + 20, 'observed_at': old}}))
    usage_status.record_claude({'rateLimitType': 'five_hour', 'utilization': .42})
    data = usage_status.claude_status({})
    assert data['five_hour']['pct'] == 42
    assert data['seven_day']['age'] >= 90000


def test_empty_or_invalid_claude_events_cannot_invent_zero(tmp_path, monkeypatch):
    import usage_status
    monkeypatch.setattr(usage_status, 'CLAUDE_CHAT_FILE', tmp_path / 'chat.json')
    for info in [{}, {'rateLimitType': 'five_hour'}, {'rateLimitType': 'five_hour', 'utilization': 'bad'}]:
        assert usage_status.record_claude(info) is None
    assert not usage_status.CLAUDE_CHAT_FILE.exists()


def test_codex_api_uses_own_quota_and_never_claude_done(tmp_path, monkeypatch, api):
    import usage_status
    monkeypatch.setattr(usage_status, '_codex_cache', {})
    monkeypatch.setattr(usage_status, '_codex_attempt', float('-inf'))
    calls = []
    def read(method, params=None):
        calls.append(method)
        return {'rateLimits': {'primary': {'usedPercent': 13, 'windowDurationMins': 300,
                                          'resetsAt': time.time() + 4000},
                               'secondary': {'usedPercent': 28, 'windowDurationMins': 10080,
                                             'resetsAt': time.time() + 50000}}}
    monkeypatch.setattr(usage_status.agent_options, 'codex_read', read)
    monkeypatch.setattr(upload, 'status', lambda: {'five_hour': {'pct': 99}, 'done': {'at': 12}})
    for _ in range(2):
        status, body = api(upload.Handler, 'GET', '/api/status?provider=codex')
        data = json.loads(body)
        assert status == 200
        assert data['provider'] == 'codex'
        assert data['five_hour']['pct'] == 13
        assert data['seven_day']['pct'] == 28
        assert 'done' not in data
    assert calls == ['account/rateLimits/read']


def test_codex_failure_does_not_retimestamp_saved_quota(monkeypatch):
    import usage_status
    old = time.time() - 90000
    monkeypatch.setattr(usage_status, '_codex_cache', {'five_hour': {'pct': 18, 'observed_at': old}})
    monkeypatch.setattr(usage_status, '_codex_attempt', float('-inf'))
    def fail(*args, **kwargs):
        raise OSError('sensitive diagnostic')
    monkeypatch.setattr(usage_status.agent_options, 'codex_read', fail)
    data = usage_status.codex_status()
    assert data['five_hour']['age'] >= 90000
    assert data['status'] == 'unavailable'
    assert 'sensitive' not in json.dumps(data)


def test_unified_windows_keep_both_fresh_even_when_status_unchanged(tmp_path, monkeypatch):
    import usage_status
    monkeypatch.setattr(usage_status, 'CLAUDE_CHAT_FILE', tmp_path / 'chat.json')
    agent = chat.Agent()
    for pct in [.23, .24]:
        agent._translate({'type': 'rate_limit_event', 'rate_limit_info': {
            'status': 'allowed', 'unifiedWindows': {
                'five_hour': {'utilization': pct, 'resetsAt': time.time() + 300},
                'seven_day': {'utilization': .52, 'resetsAt': time.time() + 90000}}}})
    data = usage_status.claude_status({})
    assert data['five_hour']['pct'] == 24
    assert data['seven_day']['pct'] == 52
    assert agent.ring[-1]['t'] == 'quota'


def test_claude_overage_above_one_is_not_dropped(tmp_path, monkeypatch):
    import usage_status
    monkeypatch.setattr(usage_status, 'CLAUDE_CHAT_FILE', tmp_path / 'chat.json')
    data = usage_status.record_claude({'unifiedWindows': {'five_hour': {'utilization': 1.05}}})
    assert data['five_hour']['pct'] == 105
