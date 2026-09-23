import importlib.util
from pathlib import Path
import pytest


def test_health_requires_exact_revision():
    spec = importlib.util.spec_from_file_location('deploy_health', Path(__file__).parents[1] / 'deploy_health.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.healthy({'status': 'ready', 'revision': 'a'*40}, 'a'*40)
    assert not module.healthy({'status': 'ready', 'revision': 'b'*40}, 'a'*40)
    assert not module.healthy({'status': 'starting', 'revision': 'a'*40}, 'a'*40)
    assert not module.healthy('ready', 'a'*40)
