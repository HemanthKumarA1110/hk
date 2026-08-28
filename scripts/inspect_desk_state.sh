#!/bin/bash
set -euo pipefail
cd /opt/trading-bot/app

echo "=== containers ==="
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'strategy|scalping|market' || true

echo "=== config ==="
docker exec trading-redis redis-cli GET 'scalping:desk:1:nifty50:config' | head -c 5000
echo

echo "=== state summary ==="
docker exec trading-redis redis-cli GET 'scalping:desk:1:nifty50:state' > /tmp/desk_state.json
python3 <<'PY'
import json
from pathlib import Path
raw = Path('/tmp/desk_state.json').read_text()
if not raw.strip():
    print('empty state')
    raise SystemExit(0)
s = json.loads(raw)
print('trades_today', s.get('trades_today'))
print('daily_pnl', s.get('daily_pnl'))
print('stream_connected', s.get('stream_connected'))
print('last_stream_eval_at', s.get('last_stream_eval_at'))
print('active_trades', len(s.get('active_trades') or []))
for x in (s.get('signals') or [])[:8]:
    print('signal', json.dumps({k: x.get(k) for k in ['status','signal_type','strategy_id','skip_reasons','entry_time','score'] if x.get(k) is not None}))
for x in (s.get('signal_events') or [])[-10:]:
    print('event', json.dumps(x, default=str)[:700])
PY

echo "=== stream heartbeat ==="
docker exec trading-redis redis-cli GET 'scalping:stream:worker:heartbeat'
echo

echo "=== logs ==="
docker logs trading-strategy-engine --since 8h 2>&1 | grep -iE 'skip|entry failed|live entry|orb|approved|auto trading|signal' | tail -50 || true
docker logs trading-scalping-stream --since 8h 2>&1 | tail -30 || true
