import { useEffect, useMemo, useState } from 'react'
import EquityCurveChart from '../EquityCurveChart'
import MetricCard from '../MetricCard'
import { defaultStrategyCode, filterStrategiesForDesk } from '../../utils/strategyFilters'

/** Collapsible backtest module — scalping desk strategies only (SCALP-* codes). */
export default function BacktestModule({
  instrument,
  backtest,
  onRun,
  strategies = [],
  defaultOpen = false,
}) {
  const [open, setOpen] = useState(defaultOpen)
  const options = useMemo(() => {
    const filtered = filterStrategiesForDesk('scalping', strategies)
    const list =
      filtered.length > 0
        ? filtered
        : [{ code: 'SCALP-BT-001', label: 'EMA Crossover + RSI', family: 'battle' }]
    return list.map((s) => ({
      code: s.code,
      label: s.label,
      family: s.family,
    }))
  }, [strategies])
  const [form, setForm] = useState({
    from_date: new Date(Date.now() - 60 * 86400000).toISOString().slice(0, 10),
    to_date: new Date().toISOString().slice(0, 10),
    timeframe: '1m',
    strategy_code: options[0]?.code || 'SCALP-BT-001',
    ai_entry: false,
    ai_exit: false,
  })

  useEffect(() => {
    if (options.length && !options.some((o) => o.code === form.strategy_code)) {
      setForm((prev) => ({ ...prev, strategy_code: options[0].code }))
    }
  }, [options, form.strategy_code])

  const result = backtest.result
  const selected = options.find((o) => o.code === form.strategy_code)

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-slate-800/40"
      >
        <div>
          <p className="text-cyan-400 text-xs uppercase tracking-widest">Backtesting</p>
          <h3 className="font-semibold">{instrument.toUpperCase()} · Per-Strategy Backtest</h3>
          <p className="text-xs text-slate-500 mt-1">
            Scalping strategies only (SCALP-* codes) · up to 60 days (Angel One 1m)
          </p>
        </div>
        <span className="text-slate-500">{open ? '▼' : '▶'}</span>
      </button>

      {open && (
        <div className="p-4 pt-0 border-t border-slate-800 space-y-4">
          <div className="grid md:grid-cols-5 gap-3">
            <label className="text-sm md:col-span-2">
              Strategy
              <select
                value={form.strategy_code}
                onChange={(e) => setForm({ ...form, strategy_code: e.target.value })}
                className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-2 py-1.5 text-sm"
              >
                {options.map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.code} — {s.label}
                  </option>
                ))}
              </select>
              {selected && (
                <p className="text-xs text-slate-500 mt-1 capitalize">{selected.family} family</p>
              )}
            </label>
            <label className="text-sm">
              From
              <input
                type="date"
                value={form.from_date}
                onChange={(e) => setForm({ ...form, from_date: e.target.value })}
                className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-2 py-1.5"
              />
            </label>
            <label className="text-sm">
              To
              <input
                type="date"
                value={form.to_date}
                onChange={(e) => setForm({ ...form, to_date: e.target.value })}
                className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-2 py-1.5"
              />
            </label>
            <label className="text-sm">
              Timeframe
              <select
                value={form.timeframe}
                onChange={(e) => setForm({ ...form, timeframe: e.target.value })}
                className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-2 py-1.5"
              >
                <option value="1m">1m</option>
                <option value="3m">3m</option>
              </select>
            </label>
          </div>

          <div className="flex flex-wrap gap-4 text-sm text-slate-400">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={form.ai_entry}
                onChange={(e) => setForm({ ...form, ai_entry: e.target.checked })}
              />
              AI entry filter
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={form.ai_exit}
                onChange={(e) => setForm({ ...form, ai_exit: e.target.checked })}
              />
              AI dynamic exit
            </label>
            <span className="text-xs text-slate-600">
              Battle strategies skip AI entry; AI exit only cuts losers
            </span>
          </div>

          <button
            type="button"
            disabled={backtest.running || !form.strategy_code}
            onClick={() => onRun(form)}
            className="w-full rounded-lg bg-cyan-500 text-slate-950 py-2.5 font-semibold disabled:opacity-50"
          >
            {backtest.running
              ? `Running ${form.strategy_code}…`
              : `Run Backtest · ${form.strategy_code}`}
          </button>

          {backtest.running && (
            <div className="space-y-1">
              <div className="h-2 rounded-full bg-slate-800">
                <div
                  className="h-full bg-cyan-500 rounded-full transition-all"
                  style={{ width: `${Math.max(backtest.progress || 5, 5)}%` }}
                />
              </div>
              <p className="text-xs text-slate-500">
                Backtest running in background ({Math.round(backtest.progress || 0)}%)
              </p>
            </div>
          )}
          {result?.note && <p className="text-amber-400/90 text-xs">{result.note}</p>}
          {result?.warning && <p className="text-amber-400/90 text-xs">{result.warning}</p>}
          {backtest.error && <p className="text-rose-400 text-sm">{backtest.error}</p>}

          {result && (
            <>
              {(result.strategy_code || result.strategy_label) && (
                <p className="text-sm text-cyan-300">
                  Results for{' '}
                  <span className="font-mono text-amber-300">{result.strategy_code || form.strategy_code}</span>
                  {result.strategy_label ? ` · ${result.strategy_label}` : ''}
                  {(result.ai_entry || result.ai_exit) && (
                    <span className="text-slate-500">
                      {' '}
                      · AI {result.ai_entry ? 'entry' : ''}
                      {result.ai_entry && result.ai_exit ? '+' : ''}
                      {result.ai_exit ? 'exit' : ''}
                    </span>
                  )}
                </p>
              )}
              <div className="grid md:grid-cols-4 gap-3">
                <MetricCard label="Total Trades" value={result.total_trades} />
                <MetricCard label="Win Rate" value={`${result.win_rate}%`} />
                <MetricCard label="Total P&L" value={`₹${result.total_pnl}`} />
                <MetricCard label="Profit Factor" value={result.profit_factor} />
                <MetricCard label="Max Drawdown" value={`₹${result.max_drawdown}`} />
                <MetricCard label="Avg Win" value={`₹${result.avg_profit_win}`} />
                <MetricCard label="Avg Loss" value={`₹${result.avg_loss_loss}`} />
                <MetricCard label="Avg Duration" value={`${result.avg_trade_duration_bars} bars`} />
              </div>
              <EquityCurveChart
                points={(result.equity_curve || []).map((p, i) => ({
                  date: String(i),
                  equity: p.equity,
                }))}
              />
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-slate-500 border-b border-slate-800">
                      <th className="py-2 text-left">Entry</th>
                      <th className="py-2 text-left">Exit</th>
                      <th className="py-2">Type</th>
                      <th className="py-2">P&L</th>
                      <th className="py-2">Exit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(result.trades || []).slice(0, 20).map((t, i) => (
                      <tr key={i} className="border-b border-slate-800/60">
                        <td className="py-2">{t.entry_time?.slice(11, 19) || '—'}</td>
                        <td className="py-2">{t.exit_time?.slice(11, 19) || '—'}</td>
                        <td className="py-2 text-center">{t.signal_type}</td>
                        <td className={`py-2 text-center font-mono ${t.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          ₹{t.pnl}
                        </td>
                        <td className="py-2 text-center text-xs text-slate-400">{t.exit_reason || t.result}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  )
}
