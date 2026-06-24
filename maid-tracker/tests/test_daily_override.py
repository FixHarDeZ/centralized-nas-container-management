def _stored_amount(rate, frac, override):
    """Mirror toggle_daily_payment's amount rule (unit-level)."""
    if override is not None:
        if override <= 0:
            raise ValueError("amount must be > 0")
        return round(override, 2)
    return round(rate * frac, 2)


def test_override_above_computed():
    assert _stored_amount(500.0, 1.0, 800.0) == 800.0


def test_override_none_uses_computed():
    assert _stored_amount(500.0, 0.5, None) == 250.0


def test_override_zero_rejected():
    try:
        _stored_amount(500.0, 1.0, 0.0)
        assert False, "expected ValueError"
    except ValueError:
        pass
