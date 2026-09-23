from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_coding_worker_has_separate_storage_and_no_deploy_credentials():
    compose = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
    worker = compose['services']['ai-deck-code']
    assert worker['profiles'] == ['coding']
    assert worker['build']['target'] == 'coding'
    assert 'env_file' not in worker
    assert worker['networks'] == ['coding']
    assert not worker.get('ports')
    mounts = worker['volumes']
    assert 'code-home:/home/claude' in mounts
    assert 'code-workspaces:/workspaces' in mounts
    assert not any(any(word in mount for word in ['/work:', 'docker.sock', 'keys.txt', 'vault', '.env', 'home:/home/claude'])
                   for mount in mounts if not mount.startswith('code-home:'))
    assert 'AI_DECK_DEPLOY_TOKEN' not in str(worker)


def test_worker_entrypoint_does_not_copy_document_rules():
    source = (ROOT / 'coding-entrypoint.sh').read_text()
    assert '/work/CLAUDE.md' not in source
    assert 'gh auth git-credential' in source
    assert '/opt/ai-deck/chat.py' in source


def test_optional_nginx_coding_routes_resolve_lazily():
    source = (ROOT / 'nginx/nginx.conf').read_text()
    assert 'location /code/chat/' in source
    assert 'location /code/projects' in source
    assert 'proxy_set_header X-Desk-User $remote_user;' in source
    assert 'set $coding_chat ai-deck-code:7683;' in source


def test_coding_terminal_preserves_authenticated_owner_on_default_port():
    # The dashboard account can differ from the roster name on the default port.
    # Passing raw query args would also let clients supply a different owner.
    source = (ROOT / 'nginx/nginx.conf').read_text()
    route = source.split('location = /code/ws {', 1)[1].split('location ', 1)[0]
    assert 'if ($remote_user !~ "^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$") { return 403; }' in route
    assert '/ws?arg=$remote_user&arg=$arg_arg;' in route
    assert '$args' not in route
    entrypoint = (ROOT / 'coding-entrypoint.sh').read_text()
    assert 'coding_terminal.py "$user"' not in entrypoint
    assert 'coding_terminal.py "$primary_user"' not in entrypoint
