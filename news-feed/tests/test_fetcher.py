from unittest.mock import MagicMock, patch
import pytest
from app.fetcher import fetch_all


def _make_feed(entries):
    feed = MagicMock()
    feed.entries = entries
    return feed


def _make_entry(url, title="Test", published="2026-05-23T07:00:00"):
    e = MagicMock()
    e.get = lambda k, d="": {"link": url, "title": title, "published": published}.get(k, d)
    return e


@patch("app.fetcher.summarize", return_value="สรุปทดสอบ")
@patch("app.fetcher.httpx.get")
@patch("app.fetcher.feedparser.parse")
def test_fetch_all_inserts_new_articles(mock_parse, mock_get, mock_summarize, tmp_path, base_config):
    mock_parse.return_value = _make_feed([_make_entry("https://example.com/1")])
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = "<html><body><p>Article body text here</p></body></html>"
    mock_get.return_value = mock_resp

    db_path = str(tmp_path / "test.db")
    from app.models import get_conn, init_db
    conn = get_conn(db_path)
    init_db(conn)
    conn.close()

    new_ids = fetch_all(db_path, base_config)
    assert len(new_ids) == 1

    from app.models import get_conn as _get_conn, get_article
    conn2 = _get_conn(db_path)
    row = get_article(conn2, new_ids[0])
    conn2.close()
    assert row is not None
    assert row["url"] == "https://example.com/1"
    assert row["summary_th"] == "สรุปทดสอบ"


@patch("app.fetcher.summarize", return_value="สรุปทดสอบ")
@patch("app.fetcher.httpx.get")
@patch("app.fetcher.feedparser.parse")
def test_fetch_all_skips_duplicates(mock_parse, mock_get, mock_summarize, tmp_path, base_config):
    mock_parse.return_value = _make_feed([_make_entry("https://example.com/1")])
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = "<p>body</p>"
    mock_get.return_value = mock_resp

    db_path = str(tmp_path / "test2.db")
    from app.models import get_conn, init_db
    conn = get_conn(db_path)
    init_db(conn)
    conn.close()

    first = fetch_all(db_path, base_config)
    second = fetch_all(db_path, base_config)
    assert len(first) == 1
    assert len(second) == 0


@patch("app.fetcher.feedparser.parse", side_effect=Exception("network error"))
def test_fetch_all_tolerates_feed_error(mock_parse, tmp_path, base_config):
    db_path = str(tmp_path / "test3.db")
    from app.models import get_conn, init_db
    conn = get_conn(db_path)
    init_db(conn)
    conn.close()
    result = fetch_all(db_path, base_config)
    assert result == []
