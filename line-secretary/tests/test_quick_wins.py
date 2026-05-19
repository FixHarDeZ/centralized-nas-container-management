import agent


# ── URL in context ────────────────────────────────────────────────

def test_rank_context_preserves_url():
    pages = [
        {"id": "abc-123", "title": "API Token", "content": "groq key here", "url": "https://notion.so/abc123"}
    ]
    result = agent._rank_context({"pages": pages, "databases": []}, ["groq"], 50000)
    assert result["pages"][0].get("url") == "https://notion.so/abc123"


def test_rank_context_preserves_db_url():
    dbs = [
        {"id": "db-1", "title": "Passwords", "rows": [], "url": "https://notion.so/db1"}
    ]
    result = agent._rank_context({"pages": [], "databases": dbs}, ["pass"], 50000)
    assert result["databases"][0].get("url") == "https://notion.so/db1"


def test_system_prompt_has_url_instruction():
    assert "🔗" in agent.SYSTEM_PROMPT
