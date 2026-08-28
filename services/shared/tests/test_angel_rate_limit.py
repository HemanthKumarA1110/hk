from trading_shared.broker.angel_one.client import is_rate_limit_error, normalize_angel_error


def test_normalize_angel_rate_limit_json_parse_error():
    raw = "Couldn't parse the JSON response received from the server: b'Access denied because of exceeding access rate'"
    assert is_rate_limit_error(raw)
    assert "rate limit" in normalize_angel_error(raw).lower()


def test_normalize_angel_rate_limit_plain_text():
    raw = "Access denied because of exceeding access rate"
    assert is_rate_limit_error(raw)
    assert normalize_angel_error(raw) == "Angel One API rate limit exceeded. Wait a minute, then retry."
