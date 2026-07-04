"""Strategy engine metadata exposed to the UI."""

from __future__ import annotations

from trading_shared.strategies.intraday_desk.catalog import STRATEGY_CATALOG as INTRADAY_CATALOG
from trading_shared.strategies.scalping_desk.constants import STRATEGY_VERSION
from trading_shared.strategies.scalping_desk.strategy_catalog import STRATEGY_CATALOG as SCALP_CATALOG
from trading_shared.strategies.scoring import INTRADAY_MIN_SCORE, SCALPING_MIN_SCORE, SWING_MIN_SCORE
from trading_shared.strategies.swing_desk.catalog import STRATEGY_CATALOG as SWING_CATALOG

ConfirmationMeta = dict[str, str | float]

ENGINE_REGISTRY: dict[str, dict] = {
    "scalping": {
        "engine": "scalping",
        "strategy_name": "scalping_desk_v8",
        "title": "Scalping Desk",
        "summary": (
            "NIFTY & BANKNIFTY index options on 1m bars. Battle-tested, adaptive, and SMC "
            "catalog strategies with AI entry validation and loss-focused AI exits."
        ),
        "universe": "NIFTY 50 & BANKNIFTY index options (NFO)",
        "timeframes": ["1m", "3m"],
        "min_score": SCALPING_MIN_SCORE,
        "target_logic": "ATR-based quick target · tight stop · max-hold time exit · optional trail",
        "session": "09:20–10:30 & 13:30–14:45 IST (battle-tested)",
        "ai_mode": "AI Auto picks best enabled strategy · Manual fixes one catalog code",
        "strategy_count": len(SCALP_CATALOG),
        "catalog_codes": list(SCALP_CATALOG.keys()),
        "families": ["battle", "adaptive", "smc"],
        "desk_path": "/scalping/nifty50",
        "live_path": "/live",
        "confirmations": [
            {"name": "entry_validator", "weight": 0, "label": "5-factor entry checklist (EMA, RSI, VWAP, vol, session)"},
            {"name": "multi_factor_entry", "weight": 0, "label": "AI entry confirmation — vetoes weak signals only"},
            {"name": "dynamic_exit", "weight": 0, "label": "AI exit — loss-cut only; targets handled by strategy"},
            {"name": "regime_filter", "weight": 0, "label": "Market regime classifier adjusts size/targets"},
            {"name": "mtf_context", "weight": 0, "label": "Multi-timeframe trend bias filter"},
        ],
    },
    "intraday": {
        "engine": "intraday",
        "strategy_name": "intraday_desk",
        "title": "Intraday Desk",
        "summary": (
            "Modular Nifty 50 equity strategies on 5m bars. Ranked universe scan, "
            "AI/manual auto-trading, flat all positions by 3:15 PM IST."
        ),
        "universe": "Top Nifty 50 equities (performance-ranked scan)",
        "timeframes": ["5m"],
        "min_score": INTRADAY_MIN_SCORE,
        "target_logic": "Per-strategy R-multiple targets · EOD force exit 3:15 PM",
        "session": "Entries until 3:00 PM · flat by 3:15 PM IST",
        "ai_mode": "AI/manual auto-trading on Live Trading page",
        "strategy_count": len(INTRADAY_CATALOG),
        "catalog_codes": [row["code"] for row in INTRADAY_CATALOG],
        "families": ["intraday"],
        "desk_path": "/intraday",
        "live_path": "/live",
        "confirmations": [
            {"name": "entry_confirmation", "weight": 0, "label": "Multi-factor entry gate (price action, volume, ATR)"},
            {"name": "dynamic_exit", "weight": 0, "label": "VWAP reclaim & momentum fade when underwater"},
            {"name": "eod_flat", "weight": 0, "label": "Hard flat at 3:15 PM IST"},
        ],
    },
    "swing": {
        "engine": "swing",
        "strategy_name": "swing_desk",
        "title": "Swing Desk",
        "summary": (
            "Long-only Nifty 50 delivery strategies on daily bars. Portfolio backtest with "
            "max open positions, AI/manual modes, and delivery cost model."
        ),
        "universe": "Full Nifty 50 equities (ranked daily scan)",
        "timeframes": ["1d"],
        "min_score": SWING_MIN_SCORE,
        "target_logic": "Strategy exits: EMA cross, RSI mean-rev, ATR chandelier · +1R breakeven rule",
        "session": "Daily bars · multi-day holds · delivery (CNC)",
        "ai_mode": "AI ranks universe · Manual uses one SWING-* strategy",
        "strategy_count": len(SWING_CATALOG),
        "catalog_codes": [row["code"] for row in SWING_CATALOG],
        "families": ["swing"],
        "desk_path": "/swing",
        "live_path": "/live",
        "confirmations": [
            {"name": "entry_confirmation", "weight": 0, "label": "Multi-factor entry on daily structure"},
            {"name": "structure_exit", "weight": 0, "label": "Lower-highs / structure break when underwater"},
            {"name": "breakeven_rule", "weight": 0, "label": "Move stop to breakeven after +1R (swing AI exit)"},
        ],
    },
}


def engine_configs() -> list[dict]:
    return [
        {**meta, "strategy_version": STRATEGY_VERSION if meta["engine"] == "scalping" else None}
        for meta in ENGINE_REGISTRY.values()
    ]
