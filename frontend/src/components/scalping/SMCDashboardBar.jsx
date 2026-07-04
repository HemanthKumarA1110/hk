/** Live SMC tracking stats — win rate, PnL, active trade, bias. */
export default function SMCDashboardBar({ stats }) {
  if (!stats) return null

  const active = stats.active_trade
  const biasColor =
    stats.market_bias === 'bullish'
      ? 'text-emerald-400'
      : stats.market_bias === 'bearish'
        ? 'text-rose-400'
        : 'text-slate-400'

  return (
    <section className="rounded-xl border border-emerald-500/20 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div>
          <p className="text-emerald-400 text-xs uppercase tracking-widest">SMC Live Stats</p>
          <h3 className="font-semibold">{stats.strategy_name || 'SMC Scalping'}</h3>
        </div>
        <span className="text-xs rounded-full border border-slate-700 px-2 py-0.5 text-slate-400">
          {stats.strategy_family === 'smc' ? 'SMC mode' : 'Adaptive mode'}
          {stats.paper_mode ? ' · Paper' : ' · Live'}
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
        <Stat label="Win Rate" value={`${stats.win_rate ?? 0}%`} />
        <Stat
          label="Daily P&L"
          value={`₹${stats.pnl ?? 0}`}
          className={(stats.pnl || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}
        />
        <Stat label="Market Bias" value={stats.market_bias || 'neutral'} className={biasColor} />
        <Stat label="Strategy" value={stats.strategy_id || '—'} />
        <Stat
          label="Active Trade"
          value={
            active
              ? `${active.signal_type} @ ₹${Number(active.entry || active.entry_spot || 0).toFixed(0)}`
              : 'None'
          }
        />
      </div>
    </section>
  )
}

function Stat({ label, value, className = '' }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`font-medium mt-0.5 capitalize ${className}`}>{value}</p>
    </div>
  )
}
