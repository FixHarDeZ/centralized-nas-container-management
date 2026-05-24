import os
import sys

# Allow test files to import from line-secretary/
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set required env vars before any module imports Settings()
os.environ.setdefault("LINE_SECRETARY_CHANNEL_SECRET", "test_secret")
os.environ.setdefault("LINE_SECRETARY_CHANNEL_ACCESS_TOKEN", "test_token")
os.environ.setdefault("LINE_SECRETARY_ALLOWED_USER_IDS", "U123test")
os.environ.setdefault("NOTION_TOKEN", "test_notion_token")
os.environ.setdefault("NOTION_QUICK_NOTE_PAGE_ID", "test-quick-note-page-id")
