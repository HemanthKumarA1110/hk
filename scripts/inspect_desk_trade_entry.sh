#!/bin/bash
set -euo pipefail
docker exec trading-redis redis-cli GET 'scalping:desk:1:nifty50:state' > /tmp/desk_state.json
python3 <<'PY'
import json
from pathlib import Path
s = json.loads(Path('/tmp/desk_state.json').read_text())
print('=== guards context ===')
print('trades_today', s.get('trades_today'))
print('active_trades', s.get('active_trades'))
print('last_trade_at', s.get('last_trade_at'))
print('session_start_capital', s.get('session_start_capital'))
print('session_capital_source', s.get('session_capital_source'))
print('broker_cash_cached', s.get('broker_cash_cached'))
print('last_orb_confirmation', json.dumps(s.get('last_orb_confirmation') or {}, default=str)[:800])
print('=== signals with trade_entry ===')
for i, x in enumerate((s.get('signals') or [])[:15]):
    te = x.get('trade_entry')
    print(i, 'status', x.get('status'), 'type', x.get('signal_type'), 'lots', x.get('lots'))
    if te:
        print('  trade_entry', json.dumps(te, default=str)[:600])
    if x.get('skip_reasons'):
        print('  skip', x.get('skip_reasons'))
print('=== signal_events ===')
for x in (s.get('signal_events') or [])[-20:]:
    print(json.dumps(x, default=str)[:900])
print('=== trade_history today ===')
for t in (s.get('trade_history') or [])[-10:]:
    print(json.dumps({k:t.get(k) for k in ['entry_time','signal_type','status','exit_reason','pnl','strategy_id']}, default=str))
PY

echo "=== entry failed logs ==="
docker logs trading-strategy-engine --since 12h 2>&1 | grep -iE 'live entry failed|entry failed|place_order|rejected|lots_zero|Unable to size|duplicate blocked|cooldown|can_enter' | tail -60 || true

echo "=== order-engine logs ==="
docker logs trading-order-engine --since 12h 2>&1 | grep -iE 'reject|error|nifty|scalp' | tail -40 || true
