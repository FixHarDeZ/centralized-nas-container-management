"""Provider quota snapshots. Percentages come from CLI data, never token estimates."""
from datetime import datetime
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time

from claude_metadata import read as claude_read
import claude_metadata
import agent_options

CLAUDE_CHAT_FILE = Path(os.environ.get('DESK_CHAT_STATUS_FILE',
                                    str(Path.home() / '.claude/desk-chat-status.json')))
WINDOWS = ('five_hour', 'seven_day')
_claude_lock = threading.Lock()
_claude_poll_lock = threading.Lock()
_claude_attempt = float('-inf')
_claude_reason = None
_claude_ok = False
_codex_lock = threading.Lock()
_codex_cache = {}
_codex_attempt = float('-inf')
_codex_ok = False


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read_chat():
    try:
        data = json.loads(CLAUDE_CHAT_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def aged(data, provider):
    now = time.time()
    out = {'provider': provider}
    for key in WINDOWS:
        win = data.get(key)
        if not isinstance(win, dict) or not number(win.get('pct')):
            continue
        observed = win.get('observed_at')
        if not number(observed):
            continue
        out[key] = dict(win, age=max(0, int(now - observed)))
    return out


def record_claude(info):
    if not isinstance(info, dict):
        return None
    windows = info.get('unifiedWindows')
    windows = dict(windows) if isinstance(windows, dict) else {}
    key = info.get('rateLimitType')
    if key in WINDOWS and key not in windows:
        windows[key] = info
    updates = {}
    for key in WINDOWS:
        win = windows.get(key)
        if not isinstance(win, dict) or not number(win.get('utilization')):
            continue
        value = win['utilization']
        if value < 0:
            continue
        reset = win.get('resetsAt')
        updates[key] = {'pct': round(value * 100, 4), 'observed_at': time.time(),
                        'resets_at': reset if number(reset) else None}
    if not updates:
        return None
    with _claude_lock:
        data = read_chat()
        data.update(updates)
        temporary = None
        try:
            CLAUDE_CHAT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', dir=CLAUDE_CHAT_FILE.parent,
                                             prefix='.desk-chat-', delete=False) as output:
                temporary = output.name
                json.dump(data, output)
            os.replace(temporary, CLAUDE_CHAT_FILE)
        except OSError:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
        return aged(data, 'claude')


def _refresh_claude(force):
    global _claude_attempt, _claude_ok, _claude_reason
    with _claude_poll_lock:
        if time.monotonic() - _claude_attempt < (15 if force else 60):
            return
        _claude_attempt = time.monotonic()
        _claude_ok, _claude_reason = False, None
        try:
            result = claude_read('get_usage')
            if not result.get('rate_limits') and claude_metadata.login_expired():
                claude_metadata.refresh_login()
                result = claude_read('get_usage')
            if result.get('rate_limits_available') is False:
                _claude_reason = 'quota_access_unavailable'
                return
            limits = result.get('rate_limits') or {}
            windows = {}
            for key in WINDOWS:
                win = limits.get(key)
                if not isinstance(win, dict) or not number(win.get('utilization')) or win['utilization'] < 0:
                    continue
                reset = win.get('resets_at')
                try:
                    reset = datetime.fromisoformat(reset.replace('Z', '+00:00')).timestamp() if isinstance(reset, str) else None
                except (ValueError, OverflowError):
                    reset = None
                # get_usage reports 0–100; stream rate_limit_event uses 0–1.
                windows[key] = {'utilization': win['utilization'] / 100, 'resetsAt': reset}
            if windows:
                record_claude({'unifiedWindows': windows})
                _claude_ok = True
        except (OSError, ValueError, TypeError, AttributeError):
            pass


def claude_status(terminal, force=False):
    _refresh_claude(force)
    now = time.time()
    merged = {}
    for key in WINDOWS:
        win = terminal.get(key)
        if isinstance(win, dict) and number(win.get('pct')):
            merged[key] = dict(win, observed_at=now - terminal.get('age', 0))
    for key, win in read_chat().items():
        if key not in WINDOWS or not isinstance(win, dict) or not number(win.get('observed_at')):
            continue
        if win['observed_at'] >= merged.get(key, {}).get('observed_at', 0):
            merged[key] = win
    out = aged(merged, 'claude')
    out['status'] = 'ok' if _claude_ok else 'unavailable'
    if _claude_reason:
        out['reason'] = _claude_reason
    if 'done' in terminal:
        out['done'] = terminal['done']
    return out


# Token Plan quota is readable only from the web console with a ~24h login
# cookie, so the chip counts locally instead. The limit is the figure another
# project hardcoded (OmniRoute XIAOMI_MIMO_MONTHLY_TOKEN_LIMIT), not Xiaomi's
# own; override it with MIMO_MONTHLY_TOKEN_LIMIT.
MIMO_MONTHLY_LIMIT = 4_100_000_000


def mimo_status():
    import mimo_backend
    now = datetime.now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    reset = start.replace(year=start.year + (start.month == 12), month=start.month % 12 + 1)
    try:
        limit = int(os.environ.get('MIMO_MONTHLY_TOKEN_LIMIT') or MIMO_MONTHLY_LIMIT)
    except ValueError:
        limit = MIMO_MONTHLY_LIMIT
    used = mimo_backend.tokens_since(int(start.timestamp() * 1000))
    return {'provider': 'mimo', 'status': 'ok', 'estimate': True,
            'five_hour': {'pct': 100 * used / limit, 'used': used, 'limit': limit, 'label': 'mo',
                          'resets_at': reset.timestamp(), 'observed_at': time.time(), 'age': 0}}


def codex_status(force=False):
    global _codex_cache, _codex_attempt, _codex_ok
    with _codex_lock:
        if time.monotonic() - _codex_attempt >= (3 if force else 30):
            _codex_attempt = time.monotonic()
            _codex_ok = False
            try:
                result = agent_options.codex_read('account/rateLimits/read')
                buckets = result.get('rateLimitsByLimitId') or {}
                limits = buckets.get('codex') or result.get('rateLimits') or {}
                updated = {}
                for key, source in [('five_hour', 'primary'), ('seven_day', 'secondary')]:
                    win = limits.get(source)
                    if not isinstance(win, dict) or not number(win.get('usedPercent')):
                        continue
                    pct = win['usedPercent']
                    if pct < 0:
                        continue
                    reset, minutes = win.get('resetsAt'), win.get('windowDurationMins')
                    updated[key] = {'pct': pct, 'observed_at': time.time(),
                                    'resets_at': reset if number(reset) else None,
                                    'window_minutes': minutes if number(minutes) else None}
                if updated:
                    _codex_cache = updated
                    _codex_ok = True
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        out = aged(_codex_cache, 'codex')
        out['status'] = 'ok' if _codex_ok else 'unavailable'
        return out
