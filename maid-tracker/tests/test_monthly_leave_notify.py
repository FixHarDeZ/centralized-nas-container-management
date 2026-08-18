"""Monthly-mode notifications must report the leave quota, not a comp/leave debt."""

import importlib

from tests.conftest import add_att, add_emp


def _nan(conn):
    """นัน's real row: promoted mid-July, anchored 1 Aug, 2 leave days a month."""
    emp_id = add_emp(
        conn,
        name="นัน",
        start_date="2026-07-05",
        monthly_salary=12000,
        holiday_mode="monthly",
        monthly_leave_days=2,
        first_month_leave_days=2,
        monthly_start_date="2026-08-01",
        employment_status="active",
    )
    add_att(conn, emp_id, "2026-07-05", "leave", half_day=1)  # probation, pre-anchor
    add_att(conn, emp_id, "2026-08-16", "leave")
    return emp_id


def test_monthly_block_shows_remaining_quota(db, monkeypatch):
    import calc
    import line_notify

    importlib.reload(calc)
    importlib.reload(line_notify)
    emp_id = _nan(db)

    b = calc.balance_snapshot(emp_id, up_to=__import__("datetime").date(2026, 8, 18))
    assert b["mode"] == "monthly"
    assert (b["total_accrued"], b["total_used"], b["balance"]) == (2.0, 1.0, 1.0)

    block = line_notify._balance_block({**b, "mode": "monthly"})
    assert "ได้รับ: 2 วัน" in block
    assert "ใช้ไป: 1 วัน" in block
    assert "คงเหลือ: +1 วัน" in block
    assert "฿" not in block  # unused quota is not money owed


def test_probation_gets_no_balance_block(db, monkeypatch):
    import calc
    import line_notify

    importlib.reload(calc)
    importlib.reload(line_notify)
    emp_id = add_emp(
        conn=db, name="ส้ม", start_date="2026-06-24", monthly_salary=10000,
        holiday_mode="monthly", monthly_leave_days=2,
        employment_status="probation", probation_daily_rate=350,
    )
    add_att(db, emp_id, "2026-06-24", "leave", half_day=1)

    b = calc.balance_snapshot(emp_id)
    assert b == {"mode": "probation"}
    assert line_notify._balance_block(b) == ""
    assert line_notify._balance_lines(b) == ""
