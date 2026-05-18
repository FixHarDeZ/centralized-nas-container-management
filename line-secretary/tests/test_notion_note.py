import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import notion


def _mock_client(response_json: dict):
    """Return a context-manager mock for httpx.AsyncClient."""
    mock_response = MagicMock()
    mock_response.json.return_value = response_json

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.patch = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.mark.asyncio
async def test_create_page_calls_correct_endpoint():
    mock_client = _mock_client({"id": "new-page-id", "object": "page", "url": "https://notion.so/x"})

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await notion.create_page("tok", "parent-page-id", "My Title")

    assert result["id"] == "new-page-id"
    mock_client.post.assert_called_once()
    args, kwargs = mock_client.post.call_args
    assert args[0].endswith("/pages")
    assert kwargs["json"]["parent"]["page_id"] == "parent-page-id"
    title_content = kwargs["json"]["properties"]["title"]["title"][0]["text"]["content"]
    assert title_content == "My Title"


@pytest.mark.asyncio
async def test_append_blocks_single_line():
    mock_client = _mock_client({"results": []})

    with patch("httpx.AsyncClient", return_value=mock_client):
        await notion.append_blocks("tok", "page-id", "Hello world")

    args, kwargs = mock_client.post.call_args
    children = kwargs["json"]["children"]
    assert len(children) == 1
    assert children[0]["type"] == "paragraph"
    assert children[0]["paragraph"]["rich_text"][0]["text"]["content"] == "Hello world"


@pytest.mark.asyncio
async def test_append_blocks_multiline():
    mock_client = _mock_client({"results": []})

    with patch("httpx.AsyncClient", return_value=mock_client):
        await notion.append_blocks("tok", "page-id", "Line 1\nLine 2\nLine 3")

    args, kwargs = mock_client.post.call_args
    children = kwargs["json"]["children"]
    assert len(children) == 3
    assert children[0]["paragraph"]["rich_text"][0]["text"]["content"] == "Line 1"
    assert children[2]["paragraph"]["rich_text"][0]["text"]["content"] == "Line 3"


@pytest.mark.asyncio
async def test_append_blocks_skips_empty_lines():
    mock_client = _mock_client({"results": []})

    with patch("httpx.AsyncClient", return_value=mock_client):
        await notion.append_blocks("tok", "page-id", "A\n\n\nB")

    args, kwargs = mock_client.post.call_args
    children = kwargs["json"]["children"]
    assert len(children) == 2
    assert children[0]["paragraph"]["rich_text"][0]["text"]["content"] == "A"
    assert children[1]["paragraph"]["rich_text"][0]["text"]["content"] == "B"


@pytest.mark.asyncio
async def test_append_blocks_all_whitespace_falls_back():
    mock_client = _mock_client({"results": []})

    with patch("httpx.AsyncClient", return_value=mock_client):
        await notion.append_blocks("tok", "page-id", "   \n  \n   ")

    args, kwargs = mock_client.post.call_args
    children = kwargs["json"]["children"]
    # Falls back to original text as single block
    assert len(children) == 1


@pytest.mark.asyncio
async def test_append_blocks_truncates_long_line():
    mock_client = _mock_client({"results": []})
    long_line = "x" * 3000

    with patch("httpx.AsyncClient", return_value=mock_client):
        await notion.append_blocks("tok", "page-id", long_line)

    args, kwargs = mock_client.post.call_args
    children = kwargs["json"]["children"]
    assert len(children[0]["paragraph"]["rich_text"][0]["text"]["content"]) == 2000
