import { useEffect, useState } from 'react'
import { fetchScalpingSignals } from '../api'
import TradingViewChart from '../components/TradingViewChart'

export default function ScalpingPage() {
  const [signals, setSignals] = useState([])

  useEffect(() => {
    const load = () => fetchScalpingSignals().then((d) => setSignals(d.signals || [])).catch(() => null)
    load()
    const timer = setInterval(load, 20000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div>
      <header className="mb-6">
        <p className="text-amber-400 text-xs uppercase tracking-widest">Scalping Desk</p>
        <h2 className="text-3xl font-bold mt-1">NIFTY / BANKNIFTY Scalps</h2>
        <p className="text-slate-400 mt-1">Multi-confirmation signals · score ≥ 80 required</p>
      </header>

      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <TradingViewChart symbol="NSE:NIFTY" interval="1" height={420} />
        <TradingViewChart symbol="NSE:BANKNIFTY" interval="1" height={420} />
      </div>

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="font-semibold mb-3">Live Scalping Signals</h3>
        <div className="space-y-2 max-h-96 overflow-auto">
          {signals.length === 0 && <p className="text-sm text-slate-500">No scalping signals yet.</p>}
          {signals.map((s) => (
            <div key={`${s.symbol}-${s.side}`} className="border border-slate-800 rounded-lg p-3 flex justify-between">
              <div>
                <p className="font-medium">{s.symbol}</p>
                <p className="text-xs text-slate-500">{s.setup || s.reason}</p>
              </div>
              <div className="text-right">
                <p className={s.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}>{s.side}</p>
                <p className="text-sm font-mono">Score {s.score}</p>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
