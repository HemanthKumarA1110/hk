#!/usr/bin/env python3
import importlib.util
from copy import deepcopy

spec = importlib.util.spec_from_file_location("opt", "/app/scripts/optimize_scalp_bt003.py")
opt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(opt)
opt.install_patches()

from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS
import trading_shared.strategies.scalping_desk.backtest as bt

bt.MAX_BACKTEST_BARS = 30000
c, _, fr, to = opt.get_candles(1)
train, val, oos = opt.split_walk_forward(c)
lot = int(INSTRUMENTS["banknifty"]["lot_size"])
capital = 100000.0
base = opt.baseline_params()

cfgs = [
    ("baseline", 9, 21, {}),
    ("ema_8_21", 8, 21, {}),
    ("ema_9_20", 9, 20, {}),
    ("put_35_45", 9, 21, {"ema_rsi_put_min": 35, "ema_rsi_put_max": 45}),
    ("ema821_put3545", 8, 21, {"ema_rsi_put_min": 35, "ema_rsi_put_max": 45}),
]
for name, f, s, tw in cfgs:
    p = deepcopy(base)
    p.update(tw)
    opt.set_ema_pair(f, s)
    opt.set_session("both")
    opt.set_allow_expiry(False)
    for ds, data in [("full", c), ("oos", oos), ("train", train), ("val", val)]:
        m = opt.metrics(opt.run_bt(data, lot, capital, p))
        print(
            f"{name:16} {ds:5} EMA{f}/{s} tr={m['trades']:3} WR={m['win_rate']:6} "
            f"PF={m['profit_factor']:5} EXP={m['expectancy']:8} PnL={m['total_pnl']:10} DD={m['max_drawdown']:9}",
            flush=True,
        )
