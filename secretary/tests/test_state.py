import sqlite3
import pytest
import ingest


@pytest.fixture
def conn():
    c = ingest.init_db(":memory:")
    yield c
    c.close()


def test_init_db_creates_table(conn):
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pages'"
    ).fetchone()
    assert tables is not None


def test_get_state_missing(conn):
    assert ingest.get_state(conn, "nonexistent") is None


def test_upsert_and_get_state(conn):
    ingest.upsert_state(conn, "page1", "2025-01-01T00:00:00.000Z", 5)
    result = ingest.get_state(conn, "page1")
    assert result == {"page_id": "page1", "last_edited_time": "2025-01-01T00:00:00.000Z", "chunk_count": 5}


def test_upsert_overwrites(conn):
    ingest.upsert_state(conn, "page1", "2025-01-01T00:00:00.000Z", 5)
    ingest.upsert_state(conn, "page1", "2025-06-01T00:00:00.000Z", 10)
    result = ingest.get_state(conn, "page1")
    assert result["last_edited_time"] == "2025-06-01T00:00:00.000Z"
    assert result["chunk_count"] == 10


def test_delete_state(conn):
    ingest.upsert_state(conn, "page1", "2025-01-01T00:00:00.000Z", 3)
    ingest.delete_state(conn, "page1")
    assert ingest.get_state(conn, "page1") is None


def test_list_all_pages(conn):
    ingest.upsert_state(conn, "p1", "2025-01-01T00:00:00.000Z", 2)
    ingest.upsert_state(conn, "p2", "2025-02-01T00:00:00.000Z", 4)
    result = ingest.list_all_pages(conn)
    assert result == {
        "p1": "2025-01-01T00:00:00.000Z",
        "p2": "2025-02-01T00:00:00.000Z",
    }
