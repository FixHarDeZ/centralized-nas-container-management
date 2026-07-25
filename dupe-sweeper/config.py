import os

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "dupe-sweeper.db")

# Comma-separated absolute paths the container may scan AND delete under.
# These are the mount points inside the container (e.g. /media/porn).
SCAN_ROOTS = [r.strip() for r in os.environ.get("SCAN_ROOTS", "").split(",") if r.strip()]

# Recycle folder. MUST be on the same filesystem as the media it holds, so a
# delete is an atomic os.rename, not a cross-volume copy. Keep it inside a
# scan root (it is skipped during walks) to guarantee same-volume.
TRASH_DIR = os.environ.get("TRASH_DIR", "")

TZ = "Asia/Bangkok"
