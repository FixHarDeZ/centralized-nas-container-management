import sys
from pathlib import Path

# upload.py sits at the stack root, not in a package — the image drops it next
# to ttyd and runs it directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# Never invoke a real account's CLI from the offline unit suite.
import pytest

@pytest.fixture(autouse=True)
def offline_claude_metadata(monkeypatch):
    import agent_options
    import usage_status
    monkeypatch.setattr(agent_options, 'claude_read', lambda method: {})
    monkeypatch.setattr(agent_options, '_claude_cached', (float('-inf'), []))
    monkeypatch.setattr(usage_status, 'claude_read', lambda method: {})
    monkeypatch.setattr(usage_status, '_claude_attempt', float('-inf'))
    monkeypatch.setattr(usage_status, '_claude_ok', False)
    monkeypatch.setattr(usage_status, '_claude_reason', None)
