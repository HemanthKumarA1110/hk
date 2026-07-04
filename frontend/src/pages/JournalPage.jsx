import { useCallback, useEffect, useMemo, useState } from 'react'
import { exportAdminJournal, fetchAdminJournal, fetchJournalInsights } from '../api'
import MetricCard from '../components/MetricCard'
import {
  exportJournalExcel,
  formatJournalDateTime,
  formatQtyLots,
  todayIsoDate,
} from '../utils/journalExport'

const ENGINE_OPTIONS = [
  { value: '', label: 'All engines' },
  { value: 'scalping', label: 'Scalping' },
  { value: 'intraday', label: 'Intraday' },
  { value: 'swing', label: 'Swing' },
]

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'open', label: 'Open' },
  { value: 'closed', label: 'Closed' },
  { value: 'filled', label: 'Filled' },
  { value: 'rejected_by_risk', label: 'Rejected' },
]

const PNL_OPTIONS = [
  { value: '', label: 'All P&L' },
  { value: 'profit', label: 'Profit only' },
  { value: 'loss', label: 'Loss only' },
]

const DEFAULT_FILTERS = () => ({
  from_date: todayIsoDate(),
  to_date: todayIsoDate(),
  engine: '',
  status: '',
  pnl: '',
})

function buildParams(filters) {
  const params = {
    from_date: filters.from_date || undefined,
    to_date: filters.to_date || undefined,
    limit: 500,
  }
  if (filters.engine) params.engine = filters.engine
  if (filters.status) params.status = filters.status
  if (filters.pnl === 'profit') params.profitable = true
  if (filters.pnl === 'loss') params.profitable = false
  return params
}

export default function JournalPage() {
  const [entries, setEntries] = useState([])
  const [summary, setSummary] = useState(null)
  const [insights, setInsights] = useState(null)
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [applied, setApplied] = useState(DEFAULT_FILTERS())
  const [busy, setBusy] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)
  const [error, setError] = useState('')

  const isTodayView = applied.from_date === todayIsoDate() && applied.to_date === todayIsoDate()

  const loadEntries = useCallback(async (nextFilters) => {
    setBusy(true)
    setError('')
    try {
      const data = await fetchAdminJournal(buildParams(nextFilters))
      setEntries(data.entries || [])
      setSummary(data.summary || null)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load journal')
      setEntries([])
      setSummary(null)
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    loadEntries(applied)
    fetchJournalInsights().then(setInsights).catch(() => null)
  }, [applied, loadEntries])

  const totals = useMemo(() => {
    const closed = entries.filter((e) => e.pnl != null)
    const wins = closed.filter((e) => Number(e.pnl) > 0).length
    return {
      count: entries.length,
      pnl: summary?.total_pnl ?? closed.reduce((sum, e) => sum + Number(e.pnl || 0), 0),
      winRate: summary?.win_rate ?? (closed.length ? Math.round((wins / closed.length) * 100) : 0),
    }
  }, [entries, summary])

  const applyFilters = () => setApplied({ ...filters })

  const resetToday = () => {
    const next = DEFAULT_FILTERS()
    setFilters(next)
    setApplied(next)
  }

  const showHistory = () => {
    const next = {
      ...filters,
      from_date: '',
      to_date: '',
    }
    setFilters(next)
    setApplied(next)
  }

  const handleExportClient = () => {
    if (!entries.length) return
    exportJournalExcel(entries)
  }

  const handleExportServer = async () => {
    setExportBusy(true)
    setError('')
    try {
      const blob = await exportAdminJournal(buildParams(applied))
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `trade-journal-${applied.to_date || todayIsoDate()}.csv`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
    } catch (err) {
      handleExportClient()
      if (!entries.length) {
        setError(err.response?.data?.detail || err.message || 'Export failed')
      }
    } finally {
      setExportBusy(false)
    }
  }

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-pink-400 text-xs uppercase tracking-widest">Trade Journal</p>
          <h2 className="text-3xl font-bold mt-1">Performance Log</h2>
          <p className="text-slate-400 mt-1 max-w-2xl">
            {isTodayView
              ? "Today's trades across scalping desk, live paper orders, and recorded journal entries."
              : 'Filtered trade history with export to Excel-compatible CSV.'}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={resetToday}
            className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800"
          >
            Today
          </button>
          <button
            type="button"
            onClick={showHistory}
            className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800"
          >
            All history
          </button>
          <button
            type="button"
            onClick={handleExportServer}
            disabled={exportBusy || entries.length === 0}
            className="rounded-lg bg-pink-500 hover:bg-pink-400 text-slate-950 px-4 py-2 text-sm font-semibold disabled:opacity-50"
          >
            {exportBusy ? 'Exporting…' : 'Download Excel'}
          </button>
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-3 mb-6">
        <MetricCard label="Trades shown" value={totals.count} />
        <MetricCard
          label="Win rate"
          value={`${totals.winRate}%`}
          tone={totals.winRate >= 50 ? 'good' : 'warn'}
        />
        <MetricCard
          label="Total P&L"
          value={`₹${Number(totals.pnl || 0).toLocaleString('en-IN')}`}
          tone={(totals.pnl || 0) >= 0 ? 'good' : 'bad'}
        />
      </div>

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 mb-6">
        <h3 className="font-semibold mb-3">Filters</h3>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-5">
          <label className="text-sm block">
            <span className="text-slate-500 text-xs uppercase">From date</span>
            <input
              type="date"
              value={filters.from_date}
              onChange={(e) => setFilters({ ...filters, from_date: e.target.value })}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            />
          </label>
          <label className="text-sm block">
            <span className="text-slate-500 text-xs uppercase">To date</span>
            <input
              type="date"
              value={filters.to_date}
              onChange={(e) => setFilters({ ...filters, to_date: e.target.value })}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            />
          </label>
          <label className="text-sm block">
            <span className="text-slate-500 text-xs uppercase">Trading type</span>
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
          <label className="text-sm block">
            <span className="text-slate-500 text-xs uppercase">Profit / Loss</span>
            <select
              value={filters.pnl}
              onChange={(e) => setFilters({ ...filters, pnl: e.target.value })}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            >
              {PNL_OPTIONS.map((opt) => (
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

      {insights && (
        <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 mb-6">
          <h3 className="font-semibold mb-2">AI insights</h3>
          <ul className="text-sm text-slate-400 space-y-1">
            {(insights.insights || []).slice(0, 4).map((line) => (
              <li key={line}>• {line}</li>
            ))}
          </ul>
        </section>
      )}

      {error && <p className="text-rose-400 text-sm mb-4">{error}</p>}

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between gap-2">
          <h3 className="font-semibold">
            {isTodayView ? "Today's trades" : 'Trade history'}
          </h3>
          {busy && <span className="text-xs text-slate-500">Loading…</span>}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[960px]">
            <thead className="bg-slate-950/50 text-slate-500 text-xs uppercase">
              <tr>
                <th className="text-left p-3">Symbol</th>
                <th className="text-left p-3">Engine</th>
                <th className="text-left p-3">Side</th>
                <th className="text-right p-3">Qty / Lots</th>
                <th className="text-right p-3">P&L</th>
                <th className="text-right p-3">AI Score</th>
                <th className="text-left p-3">Status</th>
                <th className="text-left p-3">Entry DateTime</th>
                <th className="text-left p-3">Exit DateTime</th>
              </tr>
            </thead>
            <tbody>
              {!busy && entries.length === 0 && (
                <tr>
                  <td colSpan={9} className="p-8 text-center text-slate-500">
                    No trades match the current filters.
                  </td>
                </tr>
              )}
              {entries.map((e) => (
                <tr key={e.id} className="border-t border-slate-800 hover:bg-slate-950/30">
                  <td className="p-3 font-medium font-mono text-xs">{e.symbol}</td>
                  <td className="p-3 capitalize text-slate-400">{e.engine}</td>
                  <td className="p-3">
                    <span
                      className={
                        String(e.side).toUpperCase().includes('CALL') ||
                        String(e.side).toUpperCase() === 'BUY'
                          ? 'text-emerald-400'
                          : 'text-rose-400'
                      }
                    >
                      {e.side}
                    </span>
                  </td>
                  <td className="p-3 text-right font-mono">{formatQtyLots(e)}</td>
                  <td
                    className={`p-3 text-right font-mono ${
                      e.pnl == null
                        ? 'text-slate-500'
                        : Number(e.pnl) >= 0
                          ? 'text-emerald-400'
                          : 'text-rose-400'
                    }`}
                  >
                    {e.pnl == null ? '—' : `₹${Number(e.pnl).toLocaleString('en-IN')}`}
                  </td>
                  <td className="p-3 text-right">{e.ai_score ?? '—'}</td>
                  <td className="p-3">
                    <span
                      className={`text-xs px-2 py-0.5 rounded ${
                        ['open', 'active'].includes(String(e.status).toLowerCase())
                          ? 'bg-amber-500/15 text-amber-300'
                          : String(e.status).toLowerCase() === 'closed' ||
                              String(e.status).toLowerCase() === 'filled'
                            ? 'bg-emerald-500/15 text-emerald-400'
                            : 'bg-slate-800 text-slate-400'
                      }`}
                    >
                      {e.status}
                    </span>
                  </td>
                  <td className="p-3 text-slate-400 whitespace-nowrap">
                    {formatJournalDateTime(e.entry_datetime)}
                  </td>
                  <td className="p-3 text-slate-400 whitespace-nowrap">
                    {formatJournalDateTime(e.exit_datetime)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
