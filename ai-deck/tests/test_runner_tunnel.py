import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runner_tunnel import settings, ssh_command


def config():
    return dict(ssh_host='nas', socket_path='/volume2/ai-work/.runner/runner.sock',
                runner_host='127.0.0.1', runner_port=8792,
                health_local_port=18793, health_remote_port=5072)


def test_tunnel_only_exposes_health_on_local_loopback():
    command = ssh_command(config())
    assert command[command.index('-R') + 1] == '/volume2/ai-work/.runner/runner.sock:127.0.0.1:8792'
    assert command[command.index('-L') + 1] == '127.0.0.1:18793:127.0.0.1:5072'
    assert 'ExitOnForwardFailure=yes' in command
    assert 'StreamLocalBindUnlink=yes' in command


@pytest.mark.parametrize('key,value', [('ssh_host', '-oProxyCommand=bad'),
    ('socket_path', 'relative.sock'), ('socket_path', '/tmp/../etc/socket'),
    ('runner_host', 'host:123'), ('runner_port', True), ('health_local_port', 80)])
def test_invalid_operator_config_is_rejected(tmp_path, key, value):
    values = config()
    values[key] = value
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(values))
    with pytest.raises(ValueError):
        settings(path)
