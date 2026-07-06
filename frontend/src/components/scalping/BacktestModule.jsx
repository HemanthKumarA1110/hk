import { useEffect, useMemo, useState } from 'react'
import EquityCurveChart from '../EquityCurveChart'
import MetricCard from '../MetricCard'
import { filterStrategiesForDesk } from '../../utils/strategyFilters'

const MAX_BACKTEST_DAYS = 60

function defaultBacktestDates() {
  const to = new Date()
  const from = new Date(Date.now() - MAX_BACKTEST_DAYS * 86400000)
  return {
    from_date: from.toISOString().slice(0, 10),
    to_date: to.toISOString().slice(0, 10),
  }
}

function clampBacktestRange(fromDate, toDate) {
  const end = new Date(toDate)
  const start = new Date(fromDate)
  const maxMs = MAX_BACKTEST_DAYS * 86400000
  if (Number.isNaN(end.getTime()) || Number.isNaN(start.getTime())) {
    return defaultBacktestDates()
  }
  if (end - start > maxMs) {
    return {
      from_date: new Date(end.getTime() - maxMs).toISOString().slice(0, 10),
      to_date: toDate,
    }
  }
  return { from_date: fromDate, to_date: toDate }
}

/** Collapsible backtest module — scalping desk strategies only (SCALP-* codes). */
export default function BacktestModule({
  instrument,
  backtest,
  onRun,
  strategies = [],
  defaultOpen = false,
  deskCapital,
  capitalUtilizationPct = 0.95,
}) {
  const [open, setOpen] = useState(defaultOpen)
  const options = useMemo(() => {
    const filtered = filterStrategiesForDesk('scalping', strategies)
    const fallbackCode = instrument === 'banknifty' ? 'SCALP-BT-003' : 'SCALP-BT-001'
    const fallbackLabel = instrument === 'banknifty' ? 'EMA Crossover + RSI (Bank Nifty)' : 'EMA Crossover + RSI'
    const list =
      filtered.length > 0
        ? filtered
        : [{ code: fallbackCode, label: fallbackLabel, family: 'battle' }]
    return list.map((s) => ({
      code: s.code,
      label: s.label,
      family: s.family,
    }))
  }, [strategies, instrument])
  const [form, setForm] = useState({
    ...defaultBacktestDates(),
    timeframe: '1m',
    strategy_code: options[0]?.code || (instrument === 'banknifty' ? 'SCALP-BT-003' : 'SCALP-BT-001'),
    ai_entry: false,
    ai_exit: false,
  })

  const updateRange = (patch) => {
    setForm((prev) => {
      const next = { ...prev, ...patch }
      const clamped = clampBacktestRange(next.from_date, next.to_date)
      return { ...next, ...clamped }
    })
  }

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
            Angel One 1m history · last {MAX_BACKTEST_DAYS} days · Nifty & Bank Nifty use separate SCALP codes
          </p>
          {deskCapital != null && (
            <p className="text-xs text-amber-300/90 mt-1">
              Capital ₹{Number(deskCapital).toLocaleString('en-IN')} · {Math.round(Number(capitalUtilizationPct) * 100)}% utilization · lots sized from running equity
            </p>
          )}
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
                max={form.to_date}
                onChange={(e) => updateRange({ from_date: e.target.value })}
                className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-2 py-1.5"
              />
            </label>
            <label className="text-sm">
              To
              <input
                type="date"
                value={form.to_date}
                min={form.from_date}
                max={new Date().toISOString().slice(0, 10)}
                onChange={(e) => updateRange({ to_date: e.target.value })}
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
          {result?.data_insufficient && (
            <p className="text-rose-400/90 text-xs font-medium">
              Incomplete history — only {result.bars_loaded?.toLocaleString('en-IN')} bars loaded. Re-run after Angel One
              is connected; expect ~30–40 trades on a full 60-day Nifty run.
            </p>
          )}
          {result?.data_source && (
            <p className="text-xs text-slate-500">
              Data:{' '}
              {result.data_source === 'angel_one'
                ? 'Angel One live history'
                : result.data_source === 'database'
                  ? 'Cached DB (Angel One fetch failed)'
                  : result.data_source}
              {result.date_range
                ? ` · ${result.date_range.from} → ${result.date_range.to}`
                : ` · ${form.from_date} → ${form.to_date}`}
              {result.bars_loaded != null ? ` · ${result.bars_loaded.toLocaleString('en-IN')} bars` : ''}
            </p>
          )}
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
              {result.total_trades === 0 && (result.message || result.warning) && (
                <p className="text-sm text-amber-300/90 bg-amber-950/30 border border-amber-900/40 rounded-lg px-3 py-2">
                  {result.message || result.warning}
                </p>
              )}
              <div className="grid md:grid-cols-4 gap-3">
                <MetricCard
                  label="Initial Capital"
                  value={`₹${Number(result.initial_capital ?? deskCapital ?? 0).toLocaleString('en-IN')}`}
                />
                <MetricCard
                  label="Final Capital"
                  value={`₹${Number(
                    result.final_capital ??
                      (Number(result.initial_capital ?? deskCapital ?? 0) + Number(result.total_pnl ?? 0))
                  ).toLocaleString('en-IN')}`}
                />
                <MetricCard label="Total Trades" value={result.total_trades} />
                <MetricCard label="Win Rate" value={`${result.win_rate}%`} />
                <MetricCard label="Total P&L" value={`₹${Number(result.total_pnl).toLocaleString('en-IN')}`} />
                <MetricCard label="Profit Factor" value={result.profit_factor} />
                <MetricCard label="Max Drawdown" value={`₹${result.max_drawdown}`} />
                <MetricCard label="Avg Win" value={`₹${result.avg_profit_win ?? 0}`} />
                <MetricCard label="Avg Loss" value={`₹${result.avg_loss_loss ?? 0}`} />
                <MetricCard label="Avg Duration" value={`${result.avg_trade_duration_bars ?? 0} bars`} />
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
                      <th className="py-2">Lots</th>
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
                        <td className="py-2 text-center font-mono">{t.lots ?? '—'}</td>
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
