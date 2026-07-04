import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchPaperOrderHistory, fetchScalpingPaperTrades } from '../api'

function fmtTime(ts) {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleString('en-IN', { hour12: false })
  } catch {
    return String(ts).slice(0, 19)
  }
}

function resultClass(result) {
  if (result === 'win' || result === 'filled') return 'text-emerald-400'
  if (result === 'loss' || result === 'rejected') return 'text-rose-400'
  if (result === 'open') return 'text-amber-400'
  return 'text-slate-400'
}

export default function PaperOrdersPage() {
  const [rows, setRows] = useState([])
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('all')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [platform, scalping] = await Promise.all([
        fetchPaperOrderHistory().catch(() => ({ orders: [] })),
        fetchScalpingPaperTrades().catch(() => ({ trades: [], summary: {} })),
      ])
      const merged = [...(platform.orders || []), ...(scalping.trades || [])].sort((a, b) =>
        String(b.timestamp || '').localeCompare(String(a.timestamp || ''))
      )
      setRows(merged)
      const desk = scalping.summary || {}
      const plat = platform.summary || {}
      setSummary({
        total: merged.length,
        wins: (desk.wins || 0) + (plat.filled || 0),
        losses: desk.losses || 0,
        rejected: plat.rejected || 0,
        open: desk.open || 0,
        total_pnl: desk.total_pnl || 0,
      })
    } catch {
      setError('Unable to load paper order history')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, 15000)
    return () => clearInterval(timer)
  }, [load])

  const filtered = useMemo(() => {
    if (filter === 'all') return rows
    if (filter === 'scalping') return rows.filter((r) => r.source === 'scalping_desk')
    if (filter === 'platform') return rows.filter((r) => r.source === 'live_trading')
    if (filter === 'open') return rows.filter((r) => r.result === 'open')
    if (filter === 'closed') return rows.filter((r) => r.result !== 'open')
    return rows
  }, [rows, filter])

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-amber-400 text-xs uppercase tracking-widest">Paper Trading</p>
          <h2 className="text-3xl font-bold mt-1">Paper Orders & Results</h2>
          <p className="text-slate-400 mt-1">All simulated orders from the scalping desk and live trading form</p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </header>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
          <Stat label="Total" value={summary.total} />
          <Stat label="Wins / Filled" value={summary.wins} tone="emerald" />
          <Stat label="Losses" value={summary.losses} tone="rose" />
          <Stat label="Open" value={summary.open} tone="amber" />
          <Stat label="Desk P&L" value={`₹${summary.total_pnl}`} tone={summary.total_pnl >= 0 ? 'emerald' : 'rose'} />
        </div>
      )}

      <div className="flex flex-wrap gap-2 mb-4">
        {[
          ['all', 'All'],
          ['scalping', 'Scalping desk'],
          ['platform', 'Live form'],
          ['open', 'Open'],
          ['closed', 'Closed'],
        ].map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setFilter(id)}
            className={`rounded-lg px-3 py-1.5 text-xs ${
              filter === id ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' : 'border border-slate-700 text-slate-400'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {error && <p className="text-rose-400 text-sm mb-4">{error}</p>}

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-x-auto">
        <table className="w-full text-sm min-w-[900px]">
          <thead className="bg-slate-950/50 text-slate-500 text-xs uppercase">
            <tr>
              <th className="text-left p-3">Time</th>
              <th className="text-left p-3">Source</th>
              <th className="text-left p-3">Symbol</th>
              <th className="text-left p-3">Strategy</th>
              <th className="text-left p-3">Dir</th>
              <th className="text-right p-3">Entry</th>
              <th className="text-right p-3">Exit</th>
              <th className="text-right p-3">Qty</th>
              <th className="text-right p-3">P&L</th>
              <th className="text-left p-3">Result</th>
              <th className="text-left p-3">Order ID</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && !loading && (
              <tr>
                <td colSpan={11} className="p-8 text-center text-slate-500">
                  No paper orders yet. Run the scalping desk in paper mode or place orders from Live Trading.
                </td>
              </tr>
            )}
            {filtered.map((row, i) => (
              <tr key={row.order_id || `${row.source}-${i}`} className="border-t border-slate-800">
                <td className="p-3 text-slate-400 whitespace-nowrap">{fmtTime(row.timestamp)}</td>
                <td className="p-3">
                  <span className="text-xs rounded px-2 py-0.5 bg-slate-800">
                    {row.source === 'scalping_desk' ? 'Scalping' : 'Platform'}
                  </span>
                </td>
                <td className="p-3 font-medium">{row.symbol || row.instrument || '—'}</td>
                <td className="p-3 text-xs font-mono text-amber-300">{row.strategy_code || row.strategy_id || '—'}</td>
                <td className="p-3">{row.direction || row.side || '—'}</td>
                <td className="p-3 text-right font-mono">{row.entry != null ? `₹${row.entry}` : row.price != null ? `₹${row.price}` : '—'}</td>
                <td className="p-3 text-right font-mono">{row.exit != null ? `₹${row.exit}` : '—'}</td>
                <td className="p-3 text-right font-mono">{row.qty ?? '—'}</td>
                <td className={`p-3 text-right font-mono ${(row.pnl || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {row.pnl != null ? `₹${row.pnl}` : '—'}
                </td>
                <td className={`p-3 capitalize ${resultClass(row.result)}`}>{row.result || row.status || '—'}</td>
                <td className="p-3 text-xs text-slate-500 font-mono">{row.order_id || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}

function Stat({ label, value, tone }) {
  const color = tone === 'emerald' ? 'text-emerald-400' : tone === 'rose' ? 'text-rose-400' : tone === 'amber' ? 'text-amber-400' : 'text-slate-100'
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <p className="text-xs text-slate-500 uppercase">{label}</p>
      <p className={`text-xl font-bold font-mono mt-1 ${color}`}>{value}</p>
    </div>
  )
}
