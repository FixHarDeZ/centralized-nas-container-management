# game-codes Typed Config Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace bare `os.environ.get()` calls in game-codes with a pydantic `BaseSettings` class that validates env vars at startup.

**Architecture:** Create `game-codes/config.py` with a `Settings` class (pydantic BaseSettings). Instantiate as singleton at import time. Expose module-level aliases for backward compatibility so existing code needs minimal changes.

**Tech Stack:** pydantic BaseSettings, Python 3.12

## Global Constraints

- pydantic version: latest compatible with Python 3.12 (no version pin needed for new dependency)
- Env var names MUST NOT change — existing `secrets.manifest.yaml` and Docker Compose stay untouched
- Module-level aliases MUST be preserved — existing code like `TELEGRAM_TOKEN` continues to work
- Validation: fail-fast at startup (singleton at import time)
- No `env_prefix` — map field names to env vars via `alias`

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `game-codes/config.py` | Create | `Settings` class + singleton + module-level aliases |
| `game-codes/game_code_notifier.py:25-28` | Modify | Replace `os.environ.get()` with imports from `config` |
| `game-codes/requirements.txt` | Modify | Add `pydantic` |
| `game-codes/Dockerfile:9` | Modify | Add `config.py` to COPY |
| `game-codes/tests/test_runtime.py:20-54` | Modify | Patch `config.settings` instead of `os.environ` for the monkeypatch test |

---

### Task 1: Create `game-codes/config.py` with pydantic BaseSettings

**Files:**
- Create: `game-codes/config.py`

**Interfaces:**
- Consumes: env vars `GAME_CODES_TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `STATE_FILE`, `POLL_INTERVAL`
- Produces: `settings` singleton, module-level aliases `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `STATE_FILE`, `POLL_INTERVAL`

- [ ] **Step 1: Create `game-codes/config.py`**

```python
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    telegram_token: str = Field(
        ..., alias="GAME_CODES_TELEGRAM_BOT_TOKEN",
        description="Telegram bot token for game-codes notifications",
    )
    telegram_chat_id: str = Field(
        ..., alias="TELEGRAM_CHAT_ID",
        description="Telegram chat ID for game-codes notifications",
    )
    state_file: Path = Field(
        default=Path("seen_codes.json"), alias="STATE_FILE",
        description="Path to the seen-codes JSON state file",
    )
    poll_interval: int = Field(
        default=0, alias="POLL_INTERVAL", ge=0,
        description="Loop interval in seconds; 0 = run once",
    )


settings = Settings()

TELEGRAM_TOKEN = settings.telegram_token.strip()
TELEGRAM_CHAT_ID = settings.telegram_chat_id.strip()
STATE_FILE = settings.state_file
POLL_INTERVAL = settings.poll_interval
```

- [ ] **Step 2: Add pydantic to requirements.txt**

Append to `game-codes/requirements.txt`:

```
pydantic>=2.0
pydantic-settings>=2.0
```

- [ ] **Step 3: Add `config.py` to Dockerfile COPY**

In `game-codes/Dockerfile:9`, change:

```dockerfile
COPY --chown=app:app notify.py http_client.py game_code_notifier.py ./
```

to:

```dockerfile
COPY --chown=app:app config.py notify.py http_client.py game_code_notifier.py ./
```

- [ ] **Step 4: Verify import works**

Run: `cd game-codes && python3 -c "from config import settings; print(settings)"`

Expected: Prints Settings object with env var values (or defaults for STATE_FILE, POLL_INTERVAL).

---

### Task 2: Migrate `game_code_notifier.py` to use config module

**Files:**
- Modify: `game-codes/game_code_notifier.py:25-28`

**Interfaces:**
- Consumes: `config.TELEGRAM_TOKEN`, `config.TELEGRAM_CHAT_ID`, `config.STATE_FILE`, `config.POLL_INTERVAL` from Task 1
- Produces: unchanged — all downstream code uses the same variable names

- [ ] **Step 1: Replace env var reads with config imports**

In `game-codes/game_code_notifier.py`, replace lines 25-28:

```python
TELEGRAM_TOKEN = os.environ.get("GAME_CODES_TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
STATE_FILE = Path(os.environ.get("STATE_FILE", "seen_codes.json"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "0"))
```

with:

```python
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, STATE_FILE, POLL_INTERVAL
```

- [ ] **Step 2: Remove unused imports**

Remove `os` from imports if no longer used elsewhere in the file. Check: `os` is not used in any other line after removing lines 25-28.

Actually — scan the file. `os` is NOT used anywhere else after removing the `os.environ.get()` calls. Remove it from the import list.

- [ ] **Step 3: Run existing tests to verify no breakage**

Run: `cd game-codes && python3 -m pytest tests/ -v`

Expected: All 8 tests pass (parsers 5 + runtime 3).

Note: Tests may need env vars set. The test_runtime.py `test_expect_nonzero_source_alerts_once_then_recovers` test patches `g.TELEGRAM_TOKEN` etc. via monkeypatch — this will still work because the module-level aliases are just strings.

---

### Task 3: Update test to patch config.settings

**Files:**
- Modify: `game-codes/tests/test_runtime.py:20-54`

**Interfaces:**
- Consumes: `config.settings` singleton from Task 1
- Produces: test still passes with config.settings patched

- [ ] **Step 1: Update monkeypatch test**

The existing test `test_expect_nonzero_source_alerts_once_then_recovers` (line 20) patches `g.save_state` and `g.send_telegram` — these still work because the module-level functions are unchanged.

However, if any test needs to change env var behavior (e.g., testing missing token), it should patch `config.settings`:

```python
from unittest.mock import patch
from config import Settings

# Example of how to patch settings in future tests:
# monkeypatch.setattr("config.settings", Settings(
#     telegram_token="test-token",
#     telegram_chat_id="test-chat-id",
# ))
```

For now, no changes needed to existing tests — they don't read env vars directly. Just verify they pass.

- [ ] **Step 2: Run full test suite**

Run: `cd game-codes && python3 -m pytest tests/ -v`

Expected: All 8 tests pass.

---

### Task 4: Verify Docker build and final checks

**Files:**
- None (verification only)

- [ ] **Step 1: Build Docker image locally**

Run: `cd game-codes && docker build -t game-codes-test .`

Expected: Build succeeds, `config.py` is included in image.

- [ ] **Step 2: Run all tests one final time**

Run: `cd game-codes && python3 -m pytest tests/ -v`

Expected: 8/8 pass.

- [ ] **Step 3: Commit**

```bash
cd game-codes
git add config.py game_code_notifier.py requirements.txt Dockerfile tests/test_runtime.py
git commit -m "feat(game-codes): add typed config module with pydantic BaseSettings

Replace bare os.environ.get() calls with pydantic BaseSettings for
startup validation. Env var names unchanged, module-level aliases
preserved for backward compatibility."
```

---

## Summary of Changes

| Before | After |
|--------|-------|
| `os.environ.get("GAME_CODES_TELEGRAM_BOT_TOKEN", "").strip()` | `from config import TELEGRAM_TOKEN` (validated by pydantic) |
| `int(os.environ.get("POLL_INTERVAL", "0"))` | `from config import POLL_INTERVAL` (validated: ge=0) |
| No type validation, crash at runtime on bad input | Fail-fast at startup with clear error message |
| `os` imported but only used for env vars | `os` removed, cleaner imports |
