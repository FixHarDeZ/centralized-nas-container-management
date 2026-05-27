# secretary/tests/test_notion.py
import os
from unittest.mock import MagicMock, patch
import pytest
import ingest


def _make_page(page_id: str, title: str = "Test Page", last_edited: str = "2025-01-01T00:00:00.000Z") -> dict:
    return {
        "id": page_id,
        "object": "page",
        "url": f"https://notion.so/{page_id}",
        "last_edited_time": last_edited,
        "parent": {"type": "workspace", "workspace": True},
        "properties": {
            "Name": {
                "type": "title",
                "title": [{"plain_text": title}],
            }
        },
    }


def test_extract_page_meta_basic():
    page = _make_page("abc", "Hello", "2025-03-01T00:00:00.000Z")
    meta = ingest._extract_page_meta(page)
    assert meta["id"] == "abc"
    assert meta["title"] == "Hello"
    assert meta["last_edited_time"] == "2025-03-01T00:00:00.000Z"
    assert meta["tags"] == []


def test_extract_page_meta_with_tags():
    page = _make_page("abc", "Hello")
    page["properties"]["Tags"] = {
        "type": "multi_select",
        "multi_select": [{"name": "work"}, {"name": "planning"}],
    }
    meta = ingest._extract_page_meta(page)
    assert meta["tags"] == ["work", "planning"]


@patch("ingest._notion_request")
@patch("ingest.NOTION_SOURCE_TYPE", "search")
def test_list_pages_search_mode(mock_req):
    page = _make_page("p1", "Page One")
    mock_req.return_value = {"results": [page], "has_more": False}
    result = ingest.list_pages()
    assert len(result) == 1
    assert result[0]["id"] == "p1"
    assert result[0]["title"] == "Page One"


@patch("ingest.NOTION_DATABASE_ID", "db123")
@patch("ingest.NOTION_SOURCE_TYPE", "database")
@patch("ingest._notion_request")
def test_list_pages_database_mode(mock_req):
    page = _make_page("p2", "Row One")
    mock_req.return_value = {"results": [page], "has_more": False}
    result = ingest.list_pages()
    assert result[0]["id"] == "p2"


@patch("ingest.NOTION_DATABASE_ID", "")
@patch("ingest.NOTION_SOURCE_TYPE", "database")
def test_list_pages_database_mode_missing_id():
    with pytest.raises(ValueError, match="NOTION_DATABASE_ID"):
        ingest.list_pages()


@patch("ingest._notion_request")
@patch("ingest.NOTION_SOURCE_TYPE", "search")
def test_fetch_blocks_flat(mock_req):
    blocks = [
        {"id": "b1", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "hi"}]}, "has_children": False},
    ]
    mock_req.return_value = {"results": blocks, "has_more": False}
    result = ingest.fetch_blocks("page1")
    assert len(result) == 1
    assert result[0]["id"] == "b1"


@patch("ingest._notion_request")
@patch("ingest.NOTION_SOURCE_TYPE", "search")
def test_fetch_blocks_recurses_children(mock_req):
    parent_block = {
        "id": "toggle1",
        "type": "toggle",
        "toggle": {"rich_text": [{"plain_text": "Toggle"}]},
        "has_children": True,
    }
    child_block = {
        "id": "para1",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"plain_text": "child content"}]},
        "has_children": False,
    }
    mock_req.side_effect = [
        {"results": [parent_block], "has_more": False},
        {"results": [child_block], "has_more": False},
    ]
    result = ingest.fetch_blocks("page1")
    assert result[0]["_children"][0]["id"] == "para1"


@patch("ingest._notion_request")
@patch("ingest.NOTION_SOURCE_TYPE", "search")
def test_fetch_blocks_does_not_recurse_child_page(mock_req):
    child_page_block = {
        "id": "cp1",
        "type": "child_page",
        "child_page": {"title": "Sub Page"},
        "has_children": True,
    }
    mock_req.return_value = {"results": [child_page_block], "has_more": False}
    result = ingest.fetch_blocks("page1")
    assert "_children" not in result[0]
    assert mock_req.call_count == 1
