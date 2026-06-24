"""Shared SQLite backup utility using Online Backup API + gzip.

Usage:
    from sqlite_backup import backup_db
    path = backup_db("/data/app.db", "/data/backups", prefix="app")
"""
import glob
import gzip
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def backup_db(
    db_path: str,
    backup_dir: str,
    prefix: str = "backup",
    retention_days: int = 30,
    tz: str = "Asia/Bangkok",
) -> str | None:
    """Create a gzip-compressed SQLite backup via Online Backup API.

    Returns the path to the .db.gz file, or None on failure.
    Prunes backup files older than *retention_days*.
    """
    try:
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.now(ZoneInfo(tz)).strftime("%Y%m%d-%H%M%S")
        plain_path = os.path.join(backup_dir, f"{prefix}-{stamp}.db")
        gz_path = plain_path + ".gz"

        src = sqlite3.connect(db_path)
        try:
            dst = sqlite3.connect(plain_path)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()

        with open(plain_path, "rb") as fin, gzip.open(gz_path, "wb", compresslevel=6) as fout:
            import shutil
            shutil.copyfileobj(fin, fout)
        os.remove(plain_path)

        cutoff = time.time() - retention_days * 86400
        for f in glob.glob(os.path.join(backup_dir, f"{prefix}-*.db.gz")):
            try:
                if os.path.getmtime(f) < cutoff:
                    os.remove(f)
            except OSError:
                pass

        return gz_path
    except Exception as e:
        print(f"[backup] failed: {e}", flush=True)
        return None
