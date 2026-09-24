import json
import os
import sys

import agent_options
import usage_status


def test_catalog_uses_installed_versions_and_efforts(monkeypatch):
    monkeypatch.setattr(agent_options, 'claude_read', lambda method: {'models': [
        {'value': 'default', 'resolvedModel': 'claude-sonnet-5', 'displayName': 'Default'},
        {'value': 'sonnet', 'resolvedModel': 'claude-sonnet-5', 'displayName': 'Sonnet',
         'supportedEffortLevels': ['low', 'high', 'max', 'invalid']},
        {'value': 'haiku', 'resolvedModel': 'claude-haiku-4-5-20251001', 'displayName': 'Haiku'},
        {'value': 'claude-fable-5-1[1m]', 'resolvedModel': 'claude-fable-5-1', 'displayName': 'Fable'},
    ]}, raising=False)
    monkeypatch.setattr(agent_options, '_claude_cached', (float('-inf'), []), raising=False)
    models = agent_options.catalog('claude')['models']
    assert models[0]['label'] == 'Default (Sonnet 5)'
    assert models[1] == {'id': 'sonnet', 'label': 'Sonnet 5', 'efforts': ['low', 'high', 'max']}
    assert models[2]['label'] == 'Haiku 4.5'
    assert models[3]['id'] == 'claude-fable-5-1[1m]'
    assert agent_options.validate('claude', models[3]['id'], '')


def test_refresh_claude_reads_percent_scale_and_reset(monkeypatch, tmp_path):
    monkeypatch.setattr(usage_status, 'CLAUDE_CHAT_FILE', tmp_path / 'quota.json')
    monkeypatch.setattr(usage_status, '_claude_attempt', float('-inf'), raising=False)
    calls = []
    def read(method):
        calls.append(method)
        return {'rate_limits_available': True, 'rate_limits': {
            'five_hour': {'utilization': 7, 'resets_at': '2030-01-01T12:00:00+00:00'},
            'seven_day': {'utilization': 6, 'resets_at': None}}}
    monkeypatch.setattr(usage_status, 'claude_read', read, raising=False)
    data = usage_status.claude_status({}, force=True)
    assert data['five_hour']['pct'] == 7
    assert data['five_hour']['resets_at'] == 1893499200
    assert data['seven_day']['pct'] == 6
    assert data['status'] == 'ok'
    usage_status.claude_status({}, force=True)
    assert calls == ['get_usage']


def test_claude_missing_scope_reports_reason_without_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(usage_status, 'CLAUDE_CHAT_FILE', tmp_path / 'quota.json')
    monkeypatch.setattr(usage_status, '_claude_attempt', float('-inf'), raising=False)
    monkeypatch.setattr(usage_status, 'claude_read', lambda method: {
        'rate_limits_available': False, 'rate_limits': None}, raising=False)
    data = usage_status.claude_status({}, force=True)
    assert data['status'] == 'unavailable'
    assert data['reason'] == 'quota_access_unavailable'
    assert 'five_hour' not in data


def test_native_metadata_protocol_without_model_turn(tmp_path, monkeypatch):
    import claude_metadata
    cli = tmp_path / 'claude'
    cli.write_text('#!' + sys.executable + '\n' + '''
import sys,json
for line in sys.stdin:
 e=json.loads(line)
 assert e['type']=='control_request'
 method=e['request']['subtype']
 assert method in ('initialize','get_usage')
 data={'models':[]} if method=='initialize' else {'rate_limits_available':True,'rate_limits':{'five_hour':{'utilization':7}}}
 print(json.dumps({'type':'control_response','response':{'subtype':'success','request_id':e['request_id'],'response':data}}),flush=True)
''')
    cli.chmod(0o755)
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    assert claude_metadata.read('get_usage')['rate_limits']['five_hour']['utilization'] == 7


def test_chat_and_metadata_use_saved_login(monkeypatch, tmp_path):
    import claude_metadata
    import chat
    monkeypatch.setenv('CLAUDE_CODE_OAUTH_TOKEN', 'setup-token-must-not-override-login')
    monkeypatch.setenv('HOME', str(tmp_path))
    assert 'CLAUDE_CODE_OAUTH_TOKEN' not in claude_metadata.environment()
    assert claude_metadata.environment()['HOME'] == str(tmp_path)
    agent = chat.Agent(command=[sys.executable, '-c', 'import time; time.sleep(1)'], cwd=str(tmp_path))
    calls = []
    original = chat.subprocess.Popen
    def capture(*args, **kwargs):
        calls.append(kwargs['env'])
        return original(*args, **kwargs)
    monkeypatch.setattr(chat.subprocess, 'Popen', capture)
    try:
        with agent.lock:
            agent.start()
        assert 'CLAUDE_CODE_OAUTH_TOKEN' not in calls[0]
        assert calls[0]['HOME'] == str(tmp_path)
    finally:
        with agent.lock:
            agent.stop_child()


def test_native_failure_preserves_old_observation(monkeypatch, tmp_path):
    import time
    path = tmp_path / 'quota.json'
    old = time.time() - 90000
    path.write_text(json.dumps({'five_hour': {'pct': 17, 'observed_at': old}}))
    monkeypatch.setattr(usage_status, 'CLAUDE_CHAT_FILE', path)
    def fail(method):
        raise OSError('SECRET diagnostic')
    monkeypatch.setattr(usage_status, 'claude_read', fail)
    data = usage_status.claude_status({}, force=True)
    assert data['five_hour']['age'] >= 90000
    assert data['five_hour']['pct'] == 17
    assert data['status'] == 'unavailable'
    assert 'SECRET' not in json.dumps(data)
