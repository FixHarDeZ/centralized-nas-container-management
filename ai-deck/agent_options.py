"""Public model capabilities only; never expose credentials or CLI diagnostics."""
import json
import os
from pathlib import Path
import re
import select
import subprocess
import threading
import time

from claude_metadata import read as claude_read
import mimo_backend

EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')
MODEL_ID = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}(?:\[1m\])?\Z')
_lock = threading.Lock()
_claude_lock = threading.Lock()
_claude_cached = (float('-inf'), [])
_cached = (float('-inf'), [])


def auth_status():
    try:
        result = subprocess.run(['codex', 'login', 'status'], capture_output=True,
                                text=True, timeout=5)
        if result.returncode == 0:
            return {'status': 'signed_in'}
        if result.returncode == 1 and 'not logged in' in (result.stdout + result.stderr).lower():
            return {'status': 'signed_out'}
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {'status': 'unknown'}


def codex_read(method, params=None):
    """Read metadata through the installed CLI; never launch a model turn."""
    if method not in ('model/list', 'account/rateLimits/read'):
        raise ValueError('unsupported metadata request')
    proc = subprocess.Popen(['codex', 'app-server'], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        def send(payload):
            proc.stdin.write((json.dumps(payload) + '\n').encode())
            proc.stdin.flush()
        send({'id': 1, 'method': 'initialize', 'params': {
            'clientInfo': {'name': 'ai-deck', 'version': '1.0'}}})
        deadline, buffer = time.monotonic() + 8, b''
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
                if not isinstance(event, dict):
                    continue
                if event.get('id') == 1:
                    if 'error' in event:
                        return {}
                    send({'method': 'initialized'})
                    send({'id': 2, 'method': method, 'params': params or {}})
                elif event.get('id') == 2:
                    result = event.get('result')
                    return result if isinstance(result, dict) else {}
        return {}
    finally:
        proc.kill()
        proc.wait()
        proc.stdin.close()
        proc.stdout.close()


def _installed_codex_models():
    return codex_read('model/list', {'includeHidden': False}).get('data', [])


def _codex_models():
    global _cached
    with _lock:
        if time.monotonic() - _cached[0] < 60:
            return _cached[1]
        try:
            raw = _installed_codex_models()
        except (OSError, ValueError):
            raw = []
        if not raw:
            try:
                home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
                raw = json.loads((home / 'models_cache.json').read_text()).get('models', [])
            except (OSError, ValueError, AttributeError):
                raw = []
        models = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict) or item.get('hidden') or item.get('visibility') == 'hide':
                continue
            model = item.get('model') or item.get('slug')
            if not isinstance(model, str) or not MODEL_ID.fullmatch(model):
                continue
            levels = item.get('supportedReasoningEfforts', item.get('supported_reasoning_levels', []))
            efforts = [e.get('reasoningEffort', e.get('effort')) for e in levels
                       if isinstance(e, dict)] if isinstance(levels, list) else []
            models.append({'id': model,
                           'label': str(item.get('displayName') or item.get('display_name') or model),
                           'efforts': [e for e in efforts if e in EFFORTS]})
        _cached = (time.monotonic(), models)
        return models


def _claude_models():
    global _claude_cached
    with _claude_lock:
        if time.monotonic() - _claude_cached[0] < 60:
            return _claude_cached[1]
        try:
            raw = claude_read('initialize').get('models', [])
        except (OSError, ValueError):
            raw = []
        models = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            model = item.get('value')
            if not isinstance(model, str) or not MODEL_ID.fullmatch(model):
                continue
            resolved = item.get('resolvedModel', '')
            match = re.fullmatch(r'claude-([a-z]+)-(\d+(?:-\d+)*?)(?:-\d{8})?', resolved) if isinstance(resolved, str) else None
            label = (match[1].title() + ' ' + match[2].replace('-', '.')) if match else str(item.get('displayName') or model)
            levels = item.get('supportedEffortLevels', [])
            models.append({'id': '' if model == 'default' else model,
                           'label': f'Default ({label})' if model == 'default' else label,
                           'efforts': [e for e in levels if e in EFFORTS] if isinstance(levels, list) else []})
        if not models:
            # Preserve usable aliases if the installed CLI cannot answer metadata.
            models = [{'id': name, 'label': name.title() + ' (version unavailable)',
                       'efforts': [] if name == 'haiku' else ['low', 'medium', 'high']
                       + (['xhigh', 'max'] if name in ('opus', 'fable') else [])}
                      for name in ('sonnet', 'opus', 'fable', 'haiku')]
        if not any(model['id'] == '' for model in models):
            models.insert(0, {'id': '', 'label': 'Default', 'efforts': []})
        _claude_cached = (time.monotonic(), models)
        return models


def catalog(provider):
    if provider == 'claude':
        return {'models': _claude_models()}
    if provider == 'mimo':
        return {'models': mimo_backend.MODELS}
    return {'models': [{'id': '', 'label': 'Default', 'efforts': []}] + _codex_models()}


def validate(provider, model, effort):
    if not isinstance(model, str) or not isinstance(effort, str):
        return False
    if model and not MODEL_ID.fullmatch(model):
        return False
    if model == '' and effort == '':
        return True
    for option in catalog(provider)['models']:
        if model == option['id']:
            return effort == '' or effort in option['efforts']
    return False
