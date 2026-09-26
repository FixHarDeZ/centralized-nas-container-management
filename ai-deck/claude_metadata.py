"""Read public metadata from Claude's control protocol without a model turn."""
import json
import os
import select
import subprocess
import tempfile
import time


def environment():
    # Use the saved Claude login for chat and metadata alike. A setup-token
    # overrides that login and has no profile scope for get_usage.
    env = os.environ.copy()
    env.pop('CLAUDE_CODE_OAUTH_TOKEN', None)
    return env


def login_expired():
    """True when the saved login's access token is past expiry (~8h lifetime)."""
    path = os.path.join(os.path.expanduser('~'), '.claude', '.credentials.json')
    try:
        with open(path, encoding='utf-8') as source:
            expires = json.load(source)['claudeAiOauth']['expiresAt']
        return expires / 1000 < time.time() + 60
    except (OSError, ValueError, KeyError, TypeError):
        return False


def refresh_login():
    """Let the CLI refresh an expired access token; no model turn.

    The control-protocol get_usage does not refresh on its own, so after an
    idle night the quota chip stayed "unavailable" until something else ran
    claude. `claude auth status` rewrites .credentials.json (seen 2026-09-26).
    """
    try:
        subprocess.run(['claude', 'auth', 'status'], env=environment(), timeout=20,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, cwd=tempfile.gettempdir())
    except (OSError, subprocess.SubprocessError):
        pass


def read(method):
    if method not in ('initialize', 'get_usage'):
        raise ValueError('unsupported metadata request')
    proc = subprocess.Popen([
        'claude', '-p', '--input-format', 'stream-json', '--output-format', 'stream-json',
        '--verbose', '--no-session-persistence', '--strict-mcp-config',
        '--mcp-config', '{"mcpServers":{}}', '--settings', '{"disableAllHooks":true}',
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
       cwd=tempfile.gettempdir(), env=environment())
    try:
        def send(subtype):
            request = {'subtype': subtype}
            if subtype == 'get_usage':
                request['skip_behaviors'] = True
            proc.stdin.write((json.dumps({'type': 'control_request', 'request_id': subtype,
                                         'request': request}) + '\n').encode())
            proc.stdin.flush()
        send('initialize')
        deadline, buffer = time.monotonic() + 15, b''
        while time.monotonic() < deadline:
            ready, _, _ = select.select([proc.stdout], [], [], max(0, deadline - time.monotonic()))
            if not ready:
                break
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                break
            buffer += chunk
            if len(buffer) > 2_000_000:
                break
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or event.get('type') != 'control_response':
                    continue
                response = event.get('response')
                if not isinstance(response, dict):
                    continue
                if response.get('subtype') != 'success':
                    return {}
                if response.get('request_id') == method:
                    result = response.get('response')
                    return result if isinstance(result, dict) else {}
                if response.get('request_id') == 'initialize':
                    send(method)
        return {}
    finally:
        proc.kill()
        proc.wait()
        proc.stdin.close()
        proc.stdout.close()
