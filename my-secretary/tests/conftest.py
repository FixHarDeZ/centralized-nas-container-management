import os
import sys
import tempfile

# Allow test files to import from line-secretary/
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Use a temp dir for DATA_DIR so tests don't try to create /data on the local machine
_tmp_data_dir = tempfile.mkdtemp()
os.environ.setdefault("DATA_DIR", _tmp_data_dir)

# Set required env vars before any module imports Settings()
os.environ.setdefault("LINE_SECRETARY_CHANNEL_SECRET", "test_secret")
os.environ.setdefault("LINE_SECRETARY_CHANNEL_ACCESS_TOKEN", "test_token")
os.environ.setdefault("LINE_SECRETARY_ALLOWED_USER_IDS", "U123test")
os.environ.setdefault("NOTION_TOKEN", "test_notion_token")
os.environ.setdefault("NOTION_QUICK_NOTE_PAGE_ID", "test-quick-note-page-id")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_tg_token")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test_tg_secret")
os.environ.setdefault("TELEGRAM_ALLOWED_CHAT_IDS", "9999")
