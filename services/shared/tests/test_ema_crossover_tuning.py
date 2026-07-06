"""EMA crossover tuning helpers."""

from trading_shared.strategies.scalping_desk.ema_crossover_tuning import (
    EMA_CROSSOVER_BANK_DEFAULTS,
    EMA_CROSSOVER_BANK_LEGACY,
    merge_ema_crossover_params,
)


def test_merge_ema_params():
    merged = merge_ema_crossover_params({"ema_crossover": {"ema_rsi_call_min": 52}})
    assert merged["ema_rsi_call_min"] == 52
    assert merged["ema_rsi_call_max"] == EMA_CROSSOVER_BANK_DEFAULTS["ema_rsi_call_max"]


def test_tuned_defaults_tighter_rsi_than_legacy():
    assert EMA_CROSSOVER_BANK_DEFAULTS["ema_rsi_call_min"] > EMA_CROSSOVER_BANK_LEGACY["ema_rsi_call_min"]
    assert EMA_CROSSOVER_BANK_DEFAULTS["ema_rsi_call_max"] < EMA_CROSSOVER_BANK_LEGACY["ema_rsi_call_max"]
