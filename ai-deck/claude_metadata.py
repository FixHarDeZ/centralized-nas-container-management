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
