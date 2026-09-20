"""Run the actual client in Chromium at phone and desktop sizes."""
import functools
import http.server
import json
from pathlib import Path
import re
import subprocess
import threading

import pytest

from .test_stream_render import find_chrome


@pytest.mark.parametrize('harness', ['workspace_harness.html', 'quota_harness.html'])
def test_workspace_controls_and_mobile_layout(tmp_path, harness):
    chrome = find_chrome()
    if not chrome:
        pytest.skip("Chrome/Chromium unavailable")
    root = Path(__file__).resolve().parents[1]
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        result = subprocess.run([
            chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
            "--virtual-time-budget=10000", "--timeout=15000",
            "--dump-dom", base + "/tests/" + harness,
        ], capture_output=True, text=True, timeout=45)
        match = re.search(r'<pre id="result">(.*?)</pre>', result.stdout, re.S)
        assert match, result.stderr[-1000:]
        assert json.loads(match.group(1))["failures"] == []
    finally:
        server.shutdown()
        server.server_close()
