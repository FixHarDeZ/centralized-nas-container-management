def test_schema(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(employees)").fetchall()]
    assert "employment_status" in cols
    assert "probation_daily_rate" in cols
