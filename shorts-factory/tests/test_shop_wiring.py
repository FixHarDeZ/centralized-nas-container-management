"""Deployment wiring stays private; orchestration never embeds account secrets."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_n8n_workflow_is_inactive_bounded_and_credentialed():
    path = ROOT / 'n8n/workflows/Shop_Flow_Studio.json'
    if not path.exists():
        pytest.skip('repository orchestration file not copied into stack image')
    flow = json.loads(path.read_text())
    assert flow['active'] is False
    assert flow['settings']['executionTimeout'] == 240
    names = {n['name'] for n in flow['nodes']}
    for source, connections in flow['connections'].items():
        assert source in names
        for targets in connections['main']:
            assert all(target['node'] in names for target in targets)
    for node in flow['nodes']:
        assert node['type'] != 'n8n-nodes-base.telegramTrigger'
        if node['type'] == 'n8n-nodes-base.httpRequest':
            assert node['parameters']['genericAuthType'] == 'httpCustomAuth'
            assert node['credentials']['httpCustomAuth']['name'] == 'Shop Flow Studio'
            assert node['maxTries'] == 3
            assert node['parameters']['options']['timeout'] == 30000
    assert 'snapshot' not in path.read_text()
    assert 'Bearer ' not in path.read_text()
    assert 'Basic ' not in path.read_text()


def test_nginx_keeps_browser_and_automation_auth_at_same_gateway():
    path = ROOT / 'shorts-factory/nginx/nginx.conf'
    if not path.exists():
        pytest.skip('gateway configuration not copied into stack image')
    config = path.read_text()
    assert 'auth_basic "shorts-factory"' in config
    assert 'auth_basic off' not in config
    assert 'location = /shop' in config and 'location /shop/' in config
    assert 'client_max_body_size 102m' in config
    assert 'proxy_set_header Host $http_host' in config
