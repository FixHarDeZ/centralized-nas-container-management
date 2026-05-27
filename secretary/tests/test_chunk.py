import ingest


def test_build_breadcrumb_title_only():
    assert ingest.build_breadcrumb("My Page") == "My Page"


def test_build_breadcrumb_with_section():
    assert ingest.build_breadcrumb("My Page", "Section A") == "My Page > Section A"


def test_build_breadcrumb_full():
    assert ingest.build_breadcrumb("My Page", "Section A", "Sub 1") == "My Page > Section A > Sub 1"


def test_chunk_empty_text():
    assert ingest.chunk_markdown("", "Page") == []


def test_chunk_whitespace_only():
    assert ingest.chunk_markdown("   \n\n  ", "Page") == []


def test_chunk_no_headings():
    text = "This is a single paragraph with some content."
    chunks = ingest.chunk_markdown(text, "My Page")
    assert len(chunks) == 1
    assert chunks[0]["chunk_index"] == 0
    assert chunks[0]["breadcrumb"] == "My Page"
    assert "single paragraph" in chunks[0]["text"]


def test_chunk_splits_on_h2():
    text = "Preamble text.\n## Section One\nContent one.\n## Section Two\nContent two."
    chunks = ingest.chunk_markdown(text, "Doc")
    assert len(chunks) == 3  # preamble + two sections
    assert "Preamble" in chunks[0]["text"]
    assert "Doc > Section One" in chunks[1]["breadcrumb"]
    assert "Doc > Section Two" in chunks[2]["breadcrumb"]


def test_chunk_indices_sequential():
    text = "Intro.\n## A\nAlpha.\n## B\nBeta."
    chunks = ingest.chunk_markdown(text, "Doc")
    indices = [c["chunk_index"] for c in chunks]
    assert indices == list(range(len(chunks)))


def test_chunk_tiny_merged_into_previous():
    # Section B has < 50 tokens — should merge into section A
    text = "## Section A\n" + ("word " * 60) + "\n## Section B\nTiny."
    chunks = ingest.chunk_markdown(text, "Doc")
    # Section B (4 tokens) merges into Section A
    assert len(chunks) == 1
    assert "Tiny" in chunks[0]["text"]
