"""Existing persistent state must survive the stack rename."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_existing_hooks_migrate_without_duplicates_or_clobbering(tmp_path):
    current = tmp_path / 'settings.json'
    current.write_text(json.dumps({
        'model': 'sonnet',
        'statusLine': {'type': 'command', 'command': 'bash /opt/claude-desk/statusline.sh'},
        'hooks': {'Stop': [
            {'hooks': [{'type': 'command', 'command': 'bash /opt/claude-desk/done-hook.sh'}]},
            {'hooks': [{'type': 'command', 'command': 'echo keep-custom-hook'}]},
        ]},
    }))
    source = (ROOT / 'entrypoint.sh').read_text()
    script = source.split('<<\'PY\'\n', 1)[1].split('\nPY\n', 1)[0]
    for _ in range(2):
        subprocess.run([sys.executable, '-c', script, str(current),
                        str(ROOT / 'claude-settings.json')], check=True)
    result = json.loads(current.read_text())
    assert result['model'] == 'sonnet'
    assert result['statusLine']['command'] == 'bash /opt/ai-deck/statusline.sh'
    commands = [h['command'] for e in result['hooks']['Stop'] for h in e['hooks']]
    assert commands.count('bash /opt/ai-deck/done-hook.sh') == 1
    assert 'echo keep-custom-hook' in commands
    assert not any('/opt/claude-desk/' in c for c in commands)


def test_compose_preserves_explicit_external_home():
    import yaml
    compose = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
    assert compose['name'] == 'ai-deck'
    assert compose['services']['ai-deck']['container_name'] == 'ai-deck'
    assert compose['volumes']['home']['external'] is True
    assert compose['volumes']['home']['name'] == '${AI_DECK_HOME_VOLUME:-claude-desk_claude_desk_home}'
    assert 'home:/home/claude' in compose['services']['ai-deck']['volumes']
