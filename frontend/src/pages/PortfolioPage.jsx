import { useEffect, useState } from 'react'
import { fetchPortfolioSummary } from '../api'
import MetricCard from '../components/MetricCard'
import RiskMeter from '../components/RiskMeter'

export default function PortfolioPage() {
  const [portfolio, setPortfolio] = useState(null)

  useEffect(() => {
    const load = () => fetchPortfolioSummary().then(setPortfolio).catch(() => null)
    load()
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [])

  const positions = portfolio?.positions || []

  return (
    <div>
      <header className="mb-6">
        <p className="text-blue-400 text-xs uppercase tracking-widest">Portfolio</p>
        <h2 className="text-3xl font-bold mt-1">Positions & Exposure</h2>
        <p className="text-slate-400 mt-1">
          Live sync from Angel One · status: {portfolio?.status || 'loading'}
        </p>
      </header>

      <div className="grid gap-4 md:grid-cols-3 mb-6">
        <MetricCard label="Portfolio Value" value={`₹${Number(portfolio?.total_value || 0).toLocaleString('en-IN')}`} />
        <MetricCard
          label="Day P&L"
          value={`₹${Number(portfolio?.day_pnl || 0).toLocaleString('en-IN')}`}
          tone={(portfolio?.day_pnl || 0) >= 0 ? 'good' : 'bad'}
        />
        <MetricCard label="Open Positions" value={positions.length} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <RiskMeter />
        <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 overflow-hidden">
          <h3 className="font-semibold mb-3">Holdings & Positions</h3>
          {positions.length === 0 && (
            <p className="text-sm text-slate-500">Connect broker to sync live portfolio data.</p>
          )}
          {positions.length > 0 && (
            <table className="w-full text-sm">
              <thead className="text-xs uppercase text-slate-500">
                <tr>
                  <th className="text-left p-2">Symbol</th>
                  <th className="text-right p-2">Qty</th>
                  <th className="text-right p-2">P&L</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={`${p.symbol}-${p.type}`} className="border-t border-slate-800">
                    <td className="p-2">{p.symbol}</td>
                    <td className="p-2 text-right">{p.qty}</td>
                    <td className={`p-2 text-right font-mono ${(p.pnl || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      ₹{Number(p.pnl || 0).toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  )
}
