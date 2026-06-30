import importlib
from datetime import date

import i18n
from tests.conftest import add_emp


def _calc():
    import calc

    importlib.reload(calc)
    return calc


def _pay(conn, emp_id, work_date, amount):
    conn.execute(
        "INSERT INTO daily_payments (employee_id, work_date, amount, paid_at) "
        "VALUES (?,?,?,?)",
        (emp_id, work_date, amount, "2026-06-30T10:00:00"),
    )
    conn.commit()


def test_probation_unpaid_amount_based(db):
    """Outstanding is per-day max(0, rate - paid); overpay on one day must NOT
    reduce another day's unpaid (matches dashboard ค้างจ่าย)."""
    calc = _calc()
    eid = add_emp(
        db, name="A", start_date="2026-06-01", monthly_salary=12000,
        employment_status="probation", probation_daily_rate=400,
    )
    up_to = date(2026, 6, 3)  # 3 default-present days = 3 × 400 = 1200

    r = calc.compute_probation_unpaid(eid, date(2026, 6, 1), 400, up_to=up_to)
    assert r == {"total_paid": 0.0, "total_unpaid": 1200.0}

    _pay(db, eid, "2026-06-01", 400)      # exact
    _pay(db, eid, "2026-06-02", 1000)     # overpay (tip) — must not cover 06-03
    r = calc.compute_probation_unpaid(eid, date(2026, 6, 1), 400, up_to=up_to)
    assert r == {"total_paid": 1400.0, "total_unpaid": 400.0}


def test_i18n_monthly_blocks():
    owed = i18n.translate_block("monthly_probation_owed", "en", name="Som", amount="167")
    assert owed == "📊 Som: 💵 outstanding ฿167"

    clear = i18n.translate_block("monthly_probation_clear", "en", name="Som")
    assert clear == "📊 Som: ✅ no outstanding"

    active = i18n.translate_block(
        "monthly", "en", name="Som", comp="+1", leave="-0.5",
        kind_pos=False, bal_days="0.5", bal_amt="167",
    )
    assert active == "📊 Som: comp +1 / leave -0.5 days\n  ⚖️ owed 0.5 days ≈ ฿167"

    # Thai returns no appended block.
    assert i18n.translate_block("monthly", "th", name="Som") is None
