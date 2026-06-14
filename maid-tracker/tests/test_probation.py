from datetime import date

from tests.conftest import add_emp, add_att


def _calc(monkeypatch):
    import importlib, calc
    importlib.reload(calc)
    return calc


def test_probation_day_boundary(db, monkeypatch):
    calc = _calc(monkeypatch)
    # not passed yet → every day is probation
    assert calc.is_probation_day(date(2026, 6, 25), None) is True
    # passed on 06-20: pre-pass = probation, on/after = monthly
    assert calc.is_probation_day(date(2026, 6, 19), date(2026, 6, 20)) is True
    assert calc.is_probation_day(date(2026, 6, 20), date(2026, 6, 20)) is False
    assert calc.is_probation_day(date(2026, 6, 21), date(2026, 6, 20)) is False
