#!/usr/bin/env python3
"""Check that the NAS serves the exact revision deployed by this runner job."""
import json
import os
import subprocess
import time
import urllib.request


def healthy(data, revision):
    return isinstance(data, dict) and data.get('status') == 'ready' and data.get('revision') == revision


def main():
    url = os.environ.get('AI_DECK_NAS_HEALTH_URL', '')
    if not url.startswith(('http://', 'https://')):
        raise SystemExit('Configure AI_DECK_NAS_HEALTH_URL on the runner host')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    for attempt in range(12):
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                raw = response.read(4097)
                if len(raw) <= 4096 and healthy(json.loads(raw), revision):
                    print('Health check passed for the requested commit')
                    return
        except (OSError, ValueError):
            pass
        if attempt < 11:
            time.sleep(5)
    raise SystemExit('Health check failed: requested revision is not ready')


if __name__ == '__main__':
    main()
