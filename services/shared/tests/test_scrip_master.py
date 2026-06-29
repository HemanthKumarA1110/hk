import pandas as pd

from trading_shared.market.scrip_master import ScripMasterService


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
