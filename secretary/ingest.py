"""Notion → Qdrant hybrid-search ingest service."""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ── CONFIG ───────────────────────────────────────────────────────────────────

QDRANT_URL      = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "secretary_notes")
STATE_DB        = os.getenv("STATE_DB", "/data/ingest_state.db")

NOTION_TOKEN        = os.getenv("NOTION_TOKEN", "")
NOTION_SOURCE_TYPE  = os.getenv("NOTION_SOURCE_TYPE", "search")
NOTION_DATABASE_ID  = os.getenv("NOTION_DATABASE_ID", "")
NOTION_ROOT_PAGE_ID = os.getenv("NOTION_ROOT_PAGE_ID", "")

logger = logging.getLogger(__name__)

_api_call_count = 0  # global counter, reset per run
