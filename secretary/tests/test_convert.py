import ingest


def _block(btype: str, text: str = "hello", **extra) -> dict:
    """Build a minimal Notion block fixture."""
    rt = [{"plain_text": text}]
    data = {"rich_text": rt, **extra}
    return {"type": btype, btype: data, "has_children": False}


def test_rt_extracts_plain_text():
    assert ingest._rt([{"plain_text": "foo"}, {"plain_text": " bar"}]) == "foo bar"


def test_rt_empty():
    assert ingest._rt([]) == ""


def test_paragraph():
    result = ingest.blocks_to_markdown([_block("paragraph", "hello world")])
    assert result == "hello world"


def test_heading_1():
    result = ingest.blocks_to_markdown([_block("heading_1", "Title")])
    assert result == "# Title"


def test_heading_2():
    result = ingest.blocks_to_markdown([_block("heading_2", "Section")])
    assert result == "## Section"


def test_heading_3():
    result = ingest.blocks_to_markdown([_block("heading_3", "Sub")])
    assert result == "### Sub"


def test_bulleted_list():
    result = ingest.blocks_to_markdown([_block("bulleted_list_item", "item")])
    assert result == "- item"


def test_numbered_list():
    blocks = [
        _block("numbered_list_item", "first"),
        _block("numbered_list_item", "second"),
    ]
    result = ingest.blocks_to_markdown(blocks)
    assert result == "1. first\n2. second"


def test_to_do_checked():
    b = _block("to_do", "done", checked=True)
    assert ingest.blocks_to_markdown([b]) == "- [x] done"


def test_to_do_unchecked():
    b = _block("to_do", "todo", checked=False)
    assert ingest.blocks_to_markdown([b]) == "- [ ] todo"


def test_quote():
    assert ingest.blocks_to_markdown([_block("quote", "wise words")]) == "> wise words"


def test_callout_with_emoji():
    b = {"type": "callout", "callout": {"rich_text": [{"plain_text": "note"}], "icon": {"emoji": "💡"}}, "has_children": False}
    assert ingest.blocks_to_markdown([b]) == "> 💡 note"


def test_code():
    b = {"type": "code", "code": {"rich_text": [{"plain_text": "x = 1"}], "language": "python"}, "has_children": False}
    assert ingest.blocks_to_markdown([b]) == "```python\nx = 1\n```"


def test_bookmark():
    b = {"type": "bookmark", "bookmark": {"url": "https://example.com", "caption": []}, "has_children": False}
    assert ingest.blocks_to_markdown([b]) == "[https://example.com](https://example.com)"


def test_image():
    b = {"type": "image", "image": {"external": {"url": "https://img.example.com/a.png"}, "caption": []}, "has_children": False}
    assert ingest.blocks_to_markdown([b]) == "![](https://img.example.com/a.png)"


def test_divider():
    assert ingest.blocks_to_markdown([{"type": "divider", "divider": {}, "has_children": False}]) == "---"


def test_child_page():
    b = {"type": "child_page", "child_page": {"title": "My Sub Page"}, "has_children": False}
    assert ingest.blocks_to_markdown([b]) == "[→ My Sub Page]"


def test_toggle_with_children():
    toggle = {
        "type": "toggle",
        "toggle": {"rich_text": [{"plain_text": "Details"}]},
        "has_children": True,
        "_children": [_block("paragraph", "inner text")],
    }
    result = ingest.blocks_to_markdown([toggle])
    assert "## Details" in result
    assert "inner text" in result


def test_table():
    rows = [
        {"type": "table_row", "table_row": {"cells": [[{"plain_text": "H1"}], [{"plain_text": "H2"}]]}, "has_children": False},
        {"type": "table_row", "table_row": {"cells": [[{"plain_text": "A"}], [{"plain_text": "B"}]]}, "has_children": False},
    ]
    table_block = {
        "type": "table",
        "table": {"has_column_header": True},
        "has_children": True,
        "_children": rows,
    }
    result = ingest.blocks_to_markdown([table_block])
    assert "| H1 | H2 |" in result
    assert "| --- | --- |" in result
    assert "| A | B |" in result


def test_unknown_block_skipped():
    b = {"type": "unsupported_xyz", "unsupported_xyz": {}, "has_children": False}
    result = ingest.blocks_to_markdown([b])
    assert result == ""
