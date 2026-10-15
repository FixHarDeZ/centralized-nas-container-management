"""The legacy bot and durable Shop worker share one encoder slot."""
from __future__ import annotations

import asyncio
import fcntl
import os
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path


def lock_path() -> Path:
    return Path(os.environ.get('OUTPUT_DIR', '/output')) / '.render.lock'


@contextmanager
def render_slot_sync():
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@asynccontextmanager
async def render_slot():
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(.2)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
