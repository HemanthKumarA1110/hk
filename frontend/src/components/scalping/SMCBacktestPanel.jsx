import { useState } from 'react'
import MetricCard from '../MetricCard'

/** 30-day SMC strategy comparison backtest panel. */
export default function SMCBacktestPanel({ instrument, smcBacktest, onApply }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({
    from_date: new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10),
    to_date: new Date().toISOString().slice(0, 10),
    optimize: false,
  })

  const result = smcBacktest.result
  const ranking = result?.ranking_table || []

  return (
    <section className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-emerald-500/10"
      >
        <div>
          <p className="text-emerald-400 text-xs uppercase tracking-widest">SMC Backtesting</p>
          <h3 className="font-semibold">{instrument.toUpperCase()} · Smart Money Concepts</h3>
          <p className="text-xs text-slate-500 mt-1">
            Compare FVG+OB+BOS · Liquidity Sweep · ORB+FVG over ~30 trading days
          </p>
        </div>
        <span className="text-slate-500">{open ? '▼' : '▶'}</span>
      </button>

      {open && (
        <div className="p-4 pt-0 border-t border-emerald-500/20 space-y-4">
          <div className="grid md:grid-cols-4 gap-3">
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
            <label className="text-sm flex items-end gap-2 pb-1">
              <input
                type="checkbox"
                checked={form.optimize}
                onChange={(e) => setForm({ ...form, optimize: e.target.checked })}
              />
              Optimize winner
            </label>
            <div className="flex items-end">
              <button
                type="button"
                disabled={smcBacktest.running}
                onClick={() => smcBacktest.run(form)}
                className="w-full rounded-lg bg-emerald-500 text-slate-950 py-2 font-semibold disabled:opacity-50"
              >
                {smcBacktest.running ? 'Running SMC backtest…' : 'Run SMC Compare'}
              </button>
            </div>
          </div>

          {smcBacktest.running && (
            <div className="space-y-1">
              <div className="h-2 rounded-full bg-slate-800">
                <div
                  className="h-full bg-emerald-500 rounded-full transition-all"
                  style={{ width: `${Math.max(smcBacktest.progress || 5, 5)}%` }}
                />
              </div>
              <p className="text-xs text-slate-500">
                Job queued — comparing strategies in background ({Math.round(smcBacktest.progress || 0)}%)
              </p>
            </div>
          )}
          {smcBacktest.error && <p className="text-rose-400 text-sm">{smcBacktest.error}</p>}

          {result?.warning && <p className="text-amber-400/90 text-xs">{result.warning}</p>}
          {(result?.load_notes || []).map((note) => (
            <p key={note} className="text-slate-500 text-xs">{note}</p>
          ))}

          {result?.explanation && (
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm">
              <p className="text-emerald-300 font-medium">Best: {result.best_strategy_label}</p>
              <p className="text-slate-400 text-xs mt-1">{result.explanation}</p>
              {result.data_source && (
                <p className="text-xs text-slate-500 mt-1">
                  Data: {result.data_source} · {result.bars_loaded} bars
                </p>
              )}
            </div>
          )}

          {ranking.length > 0 && (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-slate-500 border-b border-slate-800">
                      <th className="py-2 text-left">#</th>
                      <th className="py-2 text-left">Strategy</th>
                      <th className="py-2">Win%</th>
                      <th className="py-2">P&L</th>
                      <th className="py-2">Max DD</th>
                      <th className="py-2">R:R</th>
                      <th className="py-2">PF</th>
                      <th className="py-2">Trades</th>
                      <th className="py-2">Hold</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ranking.map((r) => (
                      <tr
                        key={r.strategy_id}
                        className={`border-b border-slate-800/60 ${r.rank === 1 ? 'bg-emerald-500/10' : ''}`}
                      >
                        <td className="py-2">{r.rank}</td>
                        <td className="py-2">{r.strategy_label}</td>
                        <td className="py-2 text-center">{r.win_rate}%</td>
                        <td
                          className={`py-2 text-center font-mono ${(r.total_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}
                        >
                          ₹{r.total_pnl}
                        </td>
                        <td className="py-2 text-center">₹{r.max_drawdown}</td>
                        <td className="py-2 text-center">{r.avg_risk_reward}</td>
                        <td className="py-2 text-center">{r.profit_factor}</td>
                        <td className="py-2 text-center">{r.total_trades}</td>
                        <td className="py-2 text-center">{r.avg_hold_minutes}m</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {result?.best_strategy && (
                <div className="grid md:grid-cols-4 gap-3">
                  <MetricCard label="Best Win Rate" value={`${result.best_strategy.win_rate}%`} />
                  <MetricCard label="Best P&L" value={`₹${result.best_strategy.total_pnl}`} />
                  <MetricCard label="Profit Factor" value={result.best_strategy.profit_factor} />
                  <MetricCard label="Max Drawdown" value={`₹${result.best_strategy.max_drawdown}`} />
                </div>
              )}

              {result?.recommendation && (
                <div className="flex flex-wrap gap-3 items-center">
                  <p className="text-xs text-slate-400 flex-1">
                    Live setup: {result.recommendation.fixed_strategy_id} · paper mode recommended first
                  </p>
                  <button
                    type="button"
                    disabled={smcBacktest.applying}
                    onClick={async () => {
                      const applied = await smcBacktest.applyWinner(result)
                      if (applied?.ok) onApply?.(applied)
                    }}
                    className="rounded-lg bg-violet-500 hover:bg-violet-400 text-white px-4 py-2 text-sm font-semibold disabled:opacity-50"
                  >
                    {smcBacktest.applying ? 'Applying…' : 'Apply Winner to Desk'}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  )
}
