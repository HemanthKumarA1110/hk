#!/usr/bin/env python3
"""Print CALL/PUT/session breakdown for recommended BT-003 config."""
import importlib.util
from copy import deepcopy

spec = importlib.util.spec_from_file_location("opt", "/app/scripts/optimize_scalp_bt003.py")
opt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(opt)
opt.install_patches()
from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS
import trading_shared.strategies.scalping_desk.backtest as bt

bt.MAX_BACKTEST_BARS = 30000
c, *_ = opt.get_candles(1)
lot = int(INSTRUMENTS["banknifty"]["lot_size"])
base = opt.baseline_params()
# Pre-apply recommended (script may still have old defaults in container)
p = deepcopy(base)
p.update({"ema_rsi_put_min": 35, "ema_rsi_put_max": 45})
opt.set_ema_pair(8, 21)
opt.set_session("both")
opt.set_allow_expiry(False)
m = opt.metrics(opt.run_bt(c, lot, 100000.0, p))
import json
print(json.dumps(m, indent=2))
