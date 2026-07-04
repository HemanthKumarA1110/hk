/** Daily P&L summary bar with loss guard and AI daily stop status. */
export default function DailyPnLBar({ summary, guards, dailyStop }) {
  const pnl = summary?.total_pnl ?? 0
  const lossPct = guards?.loss_guard_pct ?? 0
  const stopped = guards?.ai_daily_stop || dailyStop?.stop_trading || summary?.ai_stopped
  const stopReason = guards?.ai_daily_stop_reason || dailyStop?.reason

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-sm mb-4">
        <Metric label="Total P&L" value={`₹${Number(pnl).toLocaleString('en-IN')}`} positive={pnl >= 0} />
        <Metric label="Trades" value={`${summary?.trades ?? 0}${guards?.max_trades_per_day ? ` / ${guards.max_trades_per_day} max` : ''}`} />
        <Metric label="Win Rate" value={`${summary?.win_rate ?? 0}%`} />
        <Metric label="Win Streak" value={guards?.consecutive_wins ?? summary?.consecutive_wins ?? 0} />
        <Metric label="Max Loss Guard" value={`${Math.round(lossPct)}%`} warn={lossPct > 70} />
      </div>

      {stopped && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 mb-3 text-sm">
          <p className="text-emerald-400 font-medium">AI ended trading for today</p>
          <p className="text-xs text-slate-400 mt-1">{stopReason || 'Profits locked after successful streak'}</p>
          {dailyStop?.confidence > 0 && (
            <p className="text-xs text-slate-500 mt-1">Confidence {dailyStop.confidence}%</p>
          )}
        </div>
      )}

      {!stopped && dailyStop?.score > 0 && dailyStop?.score < 72 && (
        <p className="text-xs text-slate-500 mb-3">
          AI monitoring — {dailyStop.reason} (score {dailyStop.score}/72 to stop)
        </p>
      )}

      <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
        <div
          className={`h-full transition-all ${lossPct > 80 ? 'bg-rose-500' : 'bg-amber-500'}`}
          style={{ width: `${Math.min(lossPct, 100)}%` }}
        />
      </div>
      {guards?.alerts?.length > 0 && (
        <ul className="mt-3 space-y-1">
          {guards.alerts.map((a) => (
            <li key={a} className={`text-xs ${a.startsWith('AI daily stop') ? 'text-emerald-400' : 'text-rose-400'}`}>{a}</li>
          ))}
        </ul>
      )}
    </section>
  )
}

function Metric({ label, value, positive, warn }) {
  let color = 'text-slate-100'
  if (positive === true) color = 'text-emerald-400'
  if (positive === false) color = 'text-rose-400'
  if (warn) color = 'text-amber-400'
  return (
    <div>
      <p className="text-xs text-slate-500 uppercase">{label}</p>
      <p className={`text-lg font-semibold ${color}`}>{value}</p>
    </div>
  )
}
