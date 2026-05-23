import sqlite3
from typing import Generator

from fastapi import Request

from app.models import get_conn


def get_db(request: Request) -> Generator[sqlite3.Connection, None, None]:
    conn = get_conn(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()
