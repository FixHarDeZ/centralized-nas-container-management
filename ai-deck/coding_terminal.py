#!/usr/bin/env python3
"""ttyd receives the proxy-authenticated owner and optional workspace ID."""
import hashlib
import os
import re
import sys

import workspace_api


def session_name(owner, workspace=''):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', owner):
        raise ValueError('Invalid terminal owner')
    if workspace and not re.fullmatch(r'[0-9a-f]{32}', workspace):
        raise ValueError('Invalid workspace ID')
    # Unlike the document desk's slug, hashing cannot alias punctuation/case.
    return 'code-' + hashlib.sha256(owner.encode()).hexdigest()[:16] + '-' + (workspace or 'shell')


def command(owner, workspace=''):
    name = session_name(owner, workspace)
    path = workspace_api.store().get(owner, workspace)['path'] if workspace else os.environ.get('WORKSPACE_ROOT', '/workspaces')
    return ['tmux', '-f', '/etc/coding-tmux.conf', 'new-session', '-A', '-s', name, '-c', path]


def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit('Expected one workspace ID')
    try:
        args = command(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else '')
    except (ValueError, OSError):
        raise SystemExit('Workspace unavailable')
    except Exception:
        # WorkspaceError's safe API detail is unnecessary in a terminal attach.
        raise SystemExit('Workspace unavailable')
    os.execvp(args[0], args)


if __name__ == '__main__':
    main()
