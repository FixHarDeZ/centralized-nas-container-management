import os
import zoneinfo

SITE_BASE_URL = os.environ.get("INK_SITE_BASE_URL", "https://example.com")
USER_AGENT = os.environ.get("INK_USER_AGENT", "Mozilla/5.0 (X11; Linux x86_64)")

DATA_DIR = os.path.join(os.environ.get("INK_DATA_DIR", "/data"), "ink-reader")
DB_PATH = os.path.join(DATA_DIR, "ink.db")
LIBRARY_DIR = os.path.join(DATA_DIR, "library")
COVERS_DIR = os.path.join(DATA_DIR, "covers")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")

SCRAPE_INTERVAL_HOURS = int(os.environ.get("INK_SCRAPE_INTERVAL_HOURS", "6"))
MAX_NEW_PER_CYCLE = int(os.environ.get("INK_MAX_NEW_PER_CYCLE", "10"))
RETENTION_DAYS = int(os.environ.get("INK_RETENTION_DAYS", "30"))
REQUEST_DELAY_SECONDS = float(os.environ.get("INK_REQUEST_DELAY_SECONDS", "2"))

TZ = "Asia/Bangkok"
