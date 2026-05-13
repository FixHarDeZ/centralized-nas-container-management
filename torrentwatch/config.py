import os

SITE_BASE_URL  = "https://bearbit.org"
SITE_USERNAME  = os.environ.get("TORRENTWATCH_SITE_USERNAME", "")
SITE_PASSWORD  = os.environ.get("TORRENTWATCH_SITE_PASSWORD", "")
DEFAULT_URLS   = [u.strip() for u in os.environ.get("TORRENTWATCH_DEFAULT_URLS", "").split(",") if u.strip()]

DATA_DIR          = os.environ.get("DATA_DIR", "/data")
DB_PATH           = os.path.join(DATA_DIR, "torrentwatch.db")
NAS_DOWNLOADS_DIR = "/downloads"   # Docker volume mount point

TZ = "Asia/Bangkok"

# HTTP Basic Auth — reuse the same credentials as homepage Nginx
BASIC_AUTH_USER = os.environ.get("NGINX_BASIC_AUTH_USER", "")
BASIC_AUTH_PASS = os.environ.get("NGINX_BASIC_AUTH_PASS", "")

# LINE Messaging API — push notifications for keyword matches
LINE_ACCESS_TOKEN = os.environ.get("TORRENTWATCH_LINE_ACCESS_TOKEN", "")
LINE_USER_ID      = os.environ.get("TORRENTWATCH_LINE_USER_ID", "")
