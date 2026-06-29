import { useEffect, useState } from 'react'
import { fetchRiskStatus, resetRiskHalt } from '../api'

function GaugeBar({ label, value, max = 100, tone = 'emerald' }) {
  const pct = Math.min((value / max) * 100, 100)
  const colors = {
    emerald: 'bg-emerald-500',
    amber: 'bg-amber-500',
    rose: 'bg-rose-500',
  }
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-slate-400">{label}</span>
        <span className="text-slate-300">{value.toFixed ? value.toFixed(1) : value}%</span>
      </div>
      <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
        <div className={`h-full ${colors[tone]}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function RiskMeter({ compact = false }) {
  const [risk, setRisk] = useState(null)
  const [busy, setBusy] = useState(false)

  const refresh = () => fetchRiskStatus().then(setRisk).catch(() => null)

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 15000)
    return () => clearInterval(timer)
  }, [])

  const handleReset = async () => {
    setBusy(true)
    try {
      await resetRiskHalt()
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  if (!risk) {
    return <div className="text-sm text-slate-500">Loading risk controls...</div>
  }

  const dailyTone = risk.daily_loss_used_pct > 80 ? 'rose' : risk.daily_loss_used_pct > 50 ? 'amber' : 'emerald'
  const ddTone = risk.drawdown_pct > 10 ? 'rose' : risk.drawdown_pct > 5 ? 'amber' : 'emerald'

  return (
    <section className={`rounded-xl border border-slate-800 bg-slate-900/60 ${compact ? 'p-3' : 'p-4'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <div>
          <p className="text-rose-400 text-xs uppercase tracking-widest">Risk Manager</p>
          <h3 className="font-semibold">Capital Protection</h3>
        </div>
        <span
          className={`text-xs px-2 py-1 rounded-full ${
            risk.can_trade ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'
          }`}
        >
          {risk.can_trade ? 'Trading Allowed' : 'Trading Halted'}
        </span>
      </div>

      <div className="space-y-3 mb-4">
        <GaugeBar label="Daily Loss Used" value={risk.daily_loss_used_pct} tone={dailyTone} />
        <GaugeBar label="Drawdown" value={risk.drawdown_pct} max={risk.limits?.max_drawdown_pct || 15} tone={ddTone} />
        <GaugeBar label="Capital Allocated" value={risk.allocation_used_pct} max={100} tone="amber" />
      </div>

      {!compact && (
        <div className="grid grid-cols-2 gap-2 text-sm mb-4">
          <div className="rounded-lg bg-slate-950/50 p-2">
            <p className="text-slate-500 text-xs">Equity</p>
            <p className="font-mono">₹{Number(risk.state?.equity || 0).toLocaleString('en-IN')}</p>
          </div>
          <div className="rounded-lg bg-slate-950/50 p-2">
            <p className="text-slate-500 text-xs">Daily P&L</p>
            <p className={`font-mono ${(risk.state?.daily_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              ₹{Number(risk.state?.daily_pnl || 0).toLocaleString('en-IN')}
            </p>
          </div>
        </div>
      )}

      {!risk.can_trade && (
        <button
          type="button"
          onClick={handleReset}
          disabled={busy}
          className="text-xs rounded-lg border border-slate-700 px-3 py-1.5 hover:bg-slate-800"
        >
          {busy ? 'Resetting...' : 'Reset Halt (Admin)'}
        </button>
      )}
    </section>
  )
}
