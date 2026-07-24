import pytest

from app.db import init_db, get_db, close_db, SCHEMA


@pytest.mark.asyncio
async def test_schema_creates_tables(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    from app.config import _config
    import app.config
    app.config._config = None

    await init_db()
    db = await get_db()

    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in await cursor.fetchall()}
    assert {"incidents", "diagnostics", "analyses", "actions"}.issubset(tables)

    await close_db()
    app.config._config = None


@pytest.mark.asyncio
async def test_analyses_has_report_json_column(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    import app.config, app.db
    app.config._config = None
    app.db._db = None
    await app.db.init_db()
    db = await app.db.get_db()
    cols = [r[1] for r in await (await db.execute("PRAGMA table_info(analyses)")).fetchall()]
    assert "report_json" in cols


@pytest.mark.asyncio
async def test_migrate_adds_report_json_to_legacy_analyses(monkeypatch, tmp_path):
    """A DB created before report_json existed must gain the column on init."""
    import aiosqlite, app.config, app.db
    dbfile = tmp_path / "legacy.db"
    # Build a legacy analyses table WITHOUT report_json
    conn = await aiosqlite.connect(str(dbfile))
    await conn.execute(
        "CREATE TABLE analyses (id INTEGER PRIMARY KEY, incident_id INTEGER, "
        "root_cause TEXT, severity TEXT, suggested_fix TEXT, fix_commands TEXT, "
        "llm_tokens_used INTEGER)"
    )
    await conn.commit()
    await conn.close()

    monkeypatch.setenv("DB_PATH", str(dbfile))
    app.config._config = None
    app.db._db = None
    await app.db.init_db()
    db = await app.db.get_db()
    cols = [r[1] for r in await (await db.execute("PRAGMA table_info(analyses)")).fetchall()]
    assert "report_json" in cols
    await app.db.close_db()
    app.config._config = None
