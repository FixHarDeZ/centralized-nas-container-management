from unittest.mock import MagicMock, patch

from app.models import get_prices
from app.pricer import fetch_prices


def _or_response(models):
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.json.return_value = {"data": models}
    return m


@patch("app.pricer.http_get")
def test_fetch_prices_upserts_models(mock_get, tmp_path):
    mock_get.return_value = _or_response(
        [
            {
                "id": "deepseek/deepseek-chat",
                "name": "DeepSeek Chat",
                "context_length": 64000,
                "pricing": {"prompt": "0.00000014", "completion": "0.00000028"},
            },
        ],
    )
    db_path = str(tmp_path / "p.db")
    from app.models import get_conn, init_db

    conn = get_conn(db_path)
    init_db(conn)
    conn.close()

    count = fetch_prices(db_path)
    assert count == 1

    conn = get_conn(db_path)
    prices = get_prices(conn)
    conn.close()
    assert prices[0]["model_id"] == "deepseek/deepseek-chat"
    assert abs(prices[0]["prompt_price"] - 0.14) < 0.001


@patch("app.pricer.http_get", side_effect=Exception("timeout"))
def test_fetch_prices_tolerates_network_error(mock_get, tmp_path):
    db_path = str(tmp_path / "p2.db")
    from app.models import get_conn, init_db

    conn = get_conn(db_path)
    init_db(conn)
    conn.close()
    count = fetch_prices(db_path)
    assert count == 0
