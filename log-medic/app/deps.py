from fastapi import Request

from app import db


def get_db(request: Request):
    conn = db.get_conn(getattr(request.app.state, "db_path", None))
    try:
        yield conn
    finally:
        conn.close()
