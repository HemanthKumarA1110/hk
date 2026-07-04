import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  clearBacktestResults,
  exportBacktestResults,
  fetchBacktestResults,
} from '../api'
import MetricCard from '../components/MetricCard'
import {
  exportBacktestResultsExcel,
  formatRunDate,
  todayIsoDate,
} from '../utils/backtestExport'

const ENGINE_OPTIONS = [
  { value: '', label: 'All engines' },
  { value: 'scalping', label: 'Scalping' },
  { value: 'intraday', label: 'Intraday' },
  { value: 'swing', label: 'Swing' },
]

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'pending', label: 'Pending' },
  { value: 'running', label: 'Running' },
]

function buildParams(filters, { forExport = false } = {}) {
  const params = forExport ? {} : { limit: 500 }
  if (filters.run_from) params.run_from = filters.run_from
  if (filters.run_to) params.run_to = filters.run_to
  if (filters.engine) params.engine = filters.engine
  if (filters.status) params.status = filters.status
  return params
}

export default function BacktestResultsPage() {
  const [results, setResults] = useState([])
  const [filters, setFilters] = useState({
    run_from: '',
    run_to: '',
    engine: '',
    status: 'completed',
  })
  const [applied, setApplied] = useState({
    run_from: '',
    run_to: '',
    engine: '',
    status: 'completed',
  })
  const [busy, setBusy] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)
  const [clearBusy, setClearBusy] = useState(false)
  const [error, setError] = useState('')

  const loadResults = useCallback(async (nextFilters) => {
    setBusy(true)
    setError('')
    try {
      const data = await fetchBacktestResults(buildParams(nextFilters))
      setResults(data.results || [])
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load backtest results')
      setResults([])
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    loadResults(applied)
  }, [applied, loadResults])

  const summary = useMemo(() => {
    const completed = results.filter((r) => r.status === 'completed')
    const avgWin =
      completed.length > 0
        ? completed.reduce((sum, r) => sum + Number(r.win_rate || 0), 0) / completed.length
        : 0
    const totalPnl = completed.reduce((sum, r) => sum + Number(r.total_pnl || 0), 0)
    return { count: results.length, avgWin, totalPnl }
  }, [results])

  const applyFilters = () => setApplied({ ...filters })

  const setLast30Days = () => {
    const to = todayIsoDate()
    const from = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10)
    const next = { ...filters, run_from: from, run_to: to }
    setFilters(next)
    setApplied(next)
  }

  const clearDates = () => {
    const next = { ...filters, run_from: '', run_to: '' }
    setFilters(next)
    setApplied(next)
  }

  const handleExport = async () => {
    setExportBusy(true)
    setError('')
    try {
      const blob = await exportBacktestResults(buildParams(applied, { forExport: true }))
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `backtest-results-${todayIsoDate()}.csv`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
    } catch {
      if (results.length) exportBacktestResultsExcel(results)
      else setError('Nothing to export for the current filters')
    } finally {
      setExportBusy(false)
    }
  }

  const handleClearFiltered = async () => {
    if (!results.length) return
    const ok = window.confirm(
      `Permanently delete ${results.length} backtest result(s) matching the current filters? This cannot be undone.`
    )
    if (!ok) return
    setClearBusy(true)
    setError('')
    try {
      await clearBacktestResults(buildParams(applied, { forExport: true }))
      await loadResults(applied)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to clear results')
    } finally {
      setClearBusy(false)
    }
  }

  const handleClearAll = async () => {
    const ok = window.confirm(
      'Permanently delete your entire backtest history (all engines and statuses)? This cannot be undone.'
    )
    if (!ok) return
    setClearBusy(true)
    setError('')
    try {
      await clearBacktestResults({ delete_all: true })
      await loadResults(applied)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to clear history')
    } finally {
      setClearBusy(false)
    }
  }

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-orange-400 text-xs uppercase tracking-widest">Backtest Archive</p>
          <h2 className="text-3xl font-bold mt-1">Strategy Backtest Results</h2>
          <p className="text-slate-400 mt-1 max-w-2xl">
            All saved backtest runs across scalping, intraday, and swing — filter by run date, export
            to Excel, or open a run on the{' '}
            <Link to="/backtest" className="text-orange-300 hover:underline">
              Backtest hub
            </Link>
            .
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleClearFiltered}
            disabled={clearBusy || results.length === 0}
            className="rounded-lg border border-rose-500/40 text-rose-300 hover:bg-rose-500/10 px-4 py-2 text-sm font-semibold disabled:opacity-50"
          >
            {clearBusy ? 'Clearing…' : 'Clear filtered'}
          </button>
          <button
            type="button"
            onClick={handleClearAll}
            disabled={clearBusy}
            className="rounded-lg border border-rose-500/60 text-rose-400 hover:bg-rose-500/15 px-4 py-2 text-sm font-semibold disabled:opacity-50"
          >
            Clear all history
          </button>
          <button
            type="button"
            onClick={handleExport}
            disabled={exportBusy || results.length === 0}
            className="rounded-lg bg-orange-500 hover:bg-orange-400 text-slate-950 px-4 py-2 text-sm font-semibold disabled:opacity-50"
          >
            {exportBusy ? 'Exporting…' : 'Download Excel'}
          </button>
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-3 mb-6">
        <MetricCard label="Runs shown" value={summary.count} />
        <MetricCard label="Avg win rate" value={`${summary.avgWin.toFixed(1)}%`} />
        <MetricCard
          label="Combined P&L"
          value={`₹${Number(summary.totalPnl || 0).toLocaleString('en-IN')}`}
          tone={summary.totalPnl >= 0 ? 'good' : 'bad'}
        />
      </div>

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 mb-6">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <h3 className="font-semibold">Filters</h3>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={setLast30Days}
              className="text-xs text-orange-400 hover:text-orange-300"
            >
              Last 30 days
            </button>
            <button
              type="button"
              onClick={clearDates}
              className="text-xs text-slate-500 hover:text-slate-300"
            >
              All dates
            </button>
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <label className="text-sm block">
            <span className="text-slate-500 text-xs uppercase">Run from</span>
            <input
              type="date"
              value={filters.run_from}
              onChange={(e) => setFilters({ ...filters, run_from: e.target.value })}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            />
          </label>
          <label className="text-sm block">
            <span className="text-slate-500 text-xs uppercase">Run to</span>
            <input
              type="date"
              value={filters.run_to}
              onChange={(e) => setFilters({ ...filters, run_to: e.target.value })}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            />
          </label>
          <label className="text-sm block">
            <span className="text-slate-500 text-xs uppercase">Engine</span>
            <select
              value={filters.engine}
              onChange={(e) => setFilters({ ...filters, engine: e.target.value })}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            >
              {ENGINE_OPTIONS.map((opt) => (
                <option key={opt.value || 'all'} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm block">
            <span className="text-slate-500 text-xs uppercase">Status</span>
            <select
              value={filters.status}
              onChange={(e) => setFilters({ ...filters, status: e.target.value })}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            >
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt.value || 'all'} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button
          type="button"
          onClick={applyFilters}
          className="mt-4 rounded-lg bg-slate-100 hover:bg-white text-slate-950 px-4 py-2 text-sm font-semibold"
        >
          Apply filters
        </button>
      </section>

      {error && <p className="text-rose-400 text-sm mb-4">{error}</p>}

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <h3 className="font-semibold">Results table</h3>
          {busy && <span className="text-xs text-slate-500">Loading…</span>}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[1100px]">
            <thead className="bg-slate-950/50 text-slate-500 text-xs uppercase">
              <tr>
                <th className="text-left p-3">Run #</th>
                <th className="text-left p-3">Run date</th>
                <th className="text-left p-3">Engine</th>
                <th className="text-left p-3">Strategy</th>
                <th className="text-left p-3">Symbol</th>
                <th className="text-left p-3">Period</th>
                <th className="text-right p-3">Trades</th>
                <th className="text-right p-3">Win %</th>
                <th className="text-right p-3">P&L</th>
                <th className="text-right p-3">Max DD</th>
                <th className="text-right p-3">PF</th>
                <th className="text-center p-3">AI</th>
                <th className="text-left p-3">Status</th>
                <th className="text-left p-3">Source</th>
              </tr>
            </thead>
            <tbody>
              {!busy && results.length === 0 && (
                <tr>
                  <td colSpan={14} className="p-8 text-center text-slate-500">
                    No backtest results yet. Run backtests from the{' '}
                    <Link to="/backtest" className="text-orange-300 hover:underline">
                      Backtest hub
                    </Link>
                    .
                  </td>
                </tr>
              )}
              {results.map((row) => (
                <tr key={row.run_id} className="border-t border-slate-800 hover:bg-slate-950/30">
                  <td className="p-3 font-mono text-xs">
                    <Link
                      to="/backtest"
                      className="text-orange-300 hover:underline"
                      title="View on backtest hub"
                    >
                      #{row.run_id}
                    </Link>
                  </td>
                  <td className="p-3 text-slate-400 whitespace-nowrap text-xs">
                    {formatRunDate(row.created_at)}
                  </td>
                  <td className="p-3 capitalize">{row.engine}</td>
                  <td className="p-3 font-mono text-xs text-emerald-400/90">
                    {row.strategy_code || '—'}
                  </td>
                  <td className="p-3 font-mono text-xs">{row.symbol}</td>
                  <td className="p-3 text-xs text-slate-400 whitespace-nowrap">
                    {row.from_date} → {row.to_date}
                    <span className="text-slate-600 ml-1">{row.interval}</span>
                  </td>
                  <td className="p-3 text-right">{row.total_trades ?? '—'}</td>
                  <td className="p-3 text-right">
                    {row.win_rate != null ? `${Number(row.win_rate).toFixed(1)}%` : '—'}
                  </td>
                  <td
                    className={`p-3 text-right font-mono ${
                      row.total_pnl == null
                        ? 'text-slate-500'
                        : Number(row.total_pnl) >= 0
                          ? 'text-emerald-400'
                          : 'text-rose-400'
                    }`}
                  >
                    {row.total_pnl != null
                      ? `₹${Number(row.total_pnl).toLocaleString('en-IN')}`
                      : '—'}
                  </td>
                  <td className="p-3 text-right text-amber-400/90">
                    {row.max_drawdown != null ? Number(row.max_drawdown).toFixed(1) : '—'}
                  </td>
                  <td className="p-3 text-right">{row.profit_factor ?? '—'}</td>
                  <td className="p-3 text-center text-[10px] text-slate-500">
                    {row.ai_entry ? 'E' : '—'}
                    {row.ai_entry && row.ai_exit ? '+' : ''}
                    {row.ai_exit ? 'X' : ''}
                  </td>
                  <td className="p-3">
                    <span
                      className={`text-xs px-2 py-0.5 rounded ${
                        row.status === 'completed'
                          ? 'bg-emerald-500/15 text-emerald-400'
                          : row.status === 'failed'
                            ? 'bg-rose-500/15 text-rose-400'
                            : 'bg-slate-800 text-slate-400'
                      }`}
                    >
                      {row.status}
                    </span>
                  </td>
                  <td className="p-3 text-xs text-slate-500">{row.data_source || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
