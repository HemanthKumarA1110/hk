import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchPaperOrderHistory, fetchScalpingPaperTrades, resetPaperTrading } from '../api'

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

function sourceLabel(row) {
  if (row.source_label) return row.source_label
  const map = {
    scalping_desk: 'Scalping',
    intraday_desk: 'Intraday',
    swing_desk: 'Swing',
    live_trading: 'Live form',
  }
  return map[row.source] || 'Platform'
}

function sourceBadgeClass(source) {
  if (source === 'scalping_desk') return 'bg-cyan-500/15 text-cyan-300'
  if (source === 'intraday_desk') return 'bg-violet-500/15 text-violet-300'
  if (source === 'swing_desk') return 'bg-emerald-500/15 text-emerald-300'
  if (source === 'live_trading') return 'bg-slate-800 text-slate-300'
  return 'bg-slate-800 text-slate-400'
}

export default function PaperOrdersPage() {
  const [rows, setRows] = useState([])
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('all')
  const [resetting, setResetting] = useState(false)
  const [showResetModal, setShowResetModal] = useState(false)
  const [resetMessage, setResetMessage] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [platform, scalping] = await Promise.all([
        fetchPaperOrderHistory().catch(() => ({ orders: [] })),
        fetchScalpingPaperTrades().catch(() => ({ trades: [], summary: {} })),
      ])
      const platformOrders = platform.orders || []
      const platformIds = new Set(platformOrders.map((o) => o.order_id).filter(Boolean))
      const deskTrades = (scalping.trades || []).filter((t) => !platformIds.has(t.order_id))
      const merged = [...platformOrders, ...deskTrades].sort((a, b) =>
        String(b.timestamp || '').localeCompare(String(a.timestamp || ''))
      )
      setRows(merged)
      const desk = scalping.summary || {}
      const plat = platform.summary || {}
      setSummary({
        total: merged.length,
        wins: merged.filter((r) => r.result === 'win' || r.result === 'filled').length,
        losses: merged.filter((r) => r.result === 'loss').length,
        rejected: plat.rejected || 0,
        open: (desk.open || 0) + (plat.open || 0),
        total_pnl: desk.total_pnl || 0,
      })
    } catch {
      setError('Unable to load paper order history')
    } finally {
      setLoading(false)
    }
  }, [])

  const handleReset = async () => {
    setShowResetModal(false)
    setResetting(true)
    setError('')
    setResetMessage('')
    try {
      const result = await resetPaperTrading()
      setResetMessage(result?.message || 'Paper trading session reset.')
      await load()
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Unable to reset paper trading session')
    } finally {
      setResetting(false)
    }
  }

  useEffect(() => {
    load()
    const timer = setInterval(load, 15000)
    return () => clearInterval(timer)
  }, [load])

  const filtered = useMemo(() => {
    if (filter === 'all') return rows
    if (filter === 'scalping') return rows.filter((r) => r.source === 'scalping_desk')
    if (filter === 'intraday') return rows.filter((r) => r.source === 'intraday_desk')
    if (filter === 'swing') return rows.filter((r) => r.source === 'swing_desk')
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
          <p className="text-slate-400 mt-1">
            Dummy orders at live Angel One prices — open positions update every few seconds; closes use real exit quotes
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={load}
            disabled={loading || resetting}
            className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
          <button
            type="button"
            onClick={() => setShowResetModal(true)}
            disabled={loading || resetting}
            className="rounded-lg border border-rose-500/40 bg-rose-500/10 text-rose-300 px-4 py-2 text-sm hover:bg-rose-500/20 disabled:opacity-50"
          >
            {resetting ? 'Resetting…' : 'Reset'}
          </button>
        </div>
      </header>

      {resetMessage && <p className="text-emerald-400 text-sm mb-4">{resetMessage}</p>}

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
          ['scalping', 'Scalping'],
          ['intraday', 'Intraday'],
          ['swing', 'Swing'],
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
              <th className="text-right p-3">Live LTP</th>
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
                <td colSpan={12} className="p-8 text-center text-slate-500">
                  No paper orders yet. Run the scalping desk in paper mode or place orders from Live Trading.
                </td>
              </tr>
            )}
            {filtered.map((row, i) => (
              <tr key={row.order_id || `${row.source}-${i}`} className="border-t border-slate-800">
                <td className="p-3 text-slate-400 whitespace-nowrap">{fmtTime(row.timestamp)}</td>
                <td className="p-3">
                  <span className={`text-xs rounded px-2 py-0.5 ${sourceBadgeClass(row.source)}`}>
                    {sourceLabel(row)}
                  </span>
                </td>
                <td className="p-3 font-medium">{row.symbol || row.instrument || '—'}</td>
                <td className="p-3 text-xs font-mono text-amber-300">{row.strategy_code || row.strategy_id || '—'}</td>
                <td className="p-3">{row.direction || row.side || '—'}</td>
                <td className="p-3 text-right font-mono">{row.entry != null ? `₹${row.entry}` : row.price != null ? `₹${row.price}` : '—'}</td>
                <td className="p-3 text-right font-mono text-cyan-300/90">
                  {row.live_ltp != null ? `₹${row.live_ltp}` : '—'}
                </td>
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

      {showResetModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="max-w-md rounded-xl border border-slate-700 bg-slate-900 p-6">
            <h3 className="text-lg font-semibold text-rose-300">Reset paper trading?</h3>
            <p className="text-sm text-slate-400 mt-3">
              This permanently clears all paper orders, open positions, trade history, and desk daily P&L for Nifty,
              Bank Nifty, Intraday, and Swing. Auto-trading settings are kept. This cannot be undone.
            </p>
            <div className="flex gap-3 mt-6">
              <button
                type="button"
                onClick={() => setShowResetModal(false)}
                className="flex-1 rounded-lg border border-slate-700 py-2 text-sm hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleReset}
                className="flex-1 rounded-lg bg-rose-500 text-slate-950 py-2 text-sm font-semibold hover:bg-rose-400"
              >
                Reset session
              </button>
            </div>
          </div>
        </div>
      )}
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
