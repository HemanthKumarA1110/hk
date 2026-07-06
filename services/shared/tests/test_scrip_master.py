import pandas as pd

from trading_shared.market.scrip_master import (
    ScripMasterService,
    normalize_scrip_strike,
    parse_option_strike_symbol,
)


def test_search_equity_prefers_eq_over_bond():
    service = ScripMasterService()
    service._df = pd.DataFrame(
        [
            {
                "token": "111",
                "symbol": "753NTPC30E",
                "name": "NTPC NCD",
                "exch_seg": "NSE",
                "instrumenttype": "",
                "expiry": "",
                "strike": 0,
                "lotsize": 1,
            },
            {
                "token": "11630",
                "symbol": "NTPC-EQ",
                "name": "NTPC",
                "exch_seg": "NSE",
                "instrumenttype": "",
                "expiry": "",
                "strike": 0,
                "lotsize": 1,
            },
        ]
    )

    matches = service.search_equity("NTPC")
    assert len(matches) == 1
    assert matches[0].symbol == "NTPC-EQ"
    assert matches[0].token == "11630"


def test_get_equity_by_symbol_exact_match():
    service = ScripMasterService()
    service._df = pd.DataFrame(
        [
            {
                "token": "11630",
                "symbol": "NTPC-EQ",
                "name": "NTPC",
                "exch_seg": "NSE",
                "instrumenttype": "",
                "expiry": "",
                "strike": 0,
                "lotsize": 1,
            },
        ]
    )

    inst = service.get_equity_by_symbol("NTPC")
    assert inst is not None
    assert inst.symbol == "NTPC-EQ"


def test_normalize_scrip_strike_scales_index_options():
    assert normalize_scrip_strike(2440000.0, spot=24378) == 24400.0
    assert normalize_scrip_strike(24400.0, spot=24378) == 24400.0


def test_parse_option_strike_symbol():
    assert parse_option_strike_symbol("NIFTY07JUL2624250CE") == 24250.0
    assert parse_option_strike_symbol("BANKNIFTY07JUL2658300PE") == 58300.0
    assert parse_option_strike_symbol("NIFTY28JUL26FUT") is None


def test_nearest_expiry_options_filters_by_spot():
    service = ScripMasterService()
    service._df = pd.DataFrame(
        [
            {
                "token": "1",
                "symbol": "NIFTY07JUL2624000CE",
                "name": "NIFTY",
                "exch_seg": "NFO",
                "instrumenttype": "OPTIDX",
                "expiry": "07JUL2026",
                "strike": 2400000.0,
                "lotsize": 75,
            },
            {
                "token": "2",
                "symbol": "NIFTY07JUL2624400CE",
                "name": "NIFTY",
                "exch_seg": "NFO",
                "instrumenttype": "OPTIDX",
                "expiry": "07JUL2026",
                "strike": 2440000.0,
                "lotsize": 75,
            },
            {
                "token": "3",
                "symbol": "NIFTY14JUL2625000CE",
                "name": "NIFTY",
                "exch_seg": "NFO",
                "instrumenttype": "OPTIDX",
                "expiry": "14JUL2026",
                "strike": 2500000.0,
                "lotsize": 75,
            },
        ]
    )

    opts = service.nearest_expiry_options("NIFTY", spot=24378, strike_window=5)
    symbols = {o.symbol for o in opts}
    assert "NIFTY07JUL2624000CE" in symbols
    assert "NIFTY07JUL2624400CE" in symbols
    assert "NIFTY14JUL2625000CE" not in symbols
    assert all(o.strike < 100_000 for o in opts)
