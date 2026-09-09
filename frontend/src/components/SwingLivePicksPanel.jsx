import { useCallback, useEffect, useState } from 'react'
import { fetchSwingSignals, scanSwingPicks } from '../api'

function formatInr(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

function formatWhen(iso) {
  if (!iso) return null
  try {
    return new Date(iso).toLocaleString('en-IN', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  } catch {
    return iso
  }
}

function apiError(err, fallback) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  return err?.message || fallback
}

function confidencePct(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  return Math.round(n <= 1 ? n * 100 : n)
}

function ConfPill({ value }) {
  const pct = confidencePct(value)
  if (pct == null) return <span className="text-slate-500">—</span>
  const tone =
    pct >= 75
      ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
      : pct >= 65
        ? 'border-sky-500/30 bg-sky-500/10 text-sky-300'
        : 'border-amber-500/30 bg-amber-500/10 text-amber-200'
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium ${tone}`}>
      {pct}%
    </span>
  )
}

export default function SwingLivePicksPanel() {
  const [payload, setPayload] = useState(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchSwingSignals()
      setPayload(data)
    } catch (err) {
      setError(apiError(err, 'Could not load cached swing picks'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const runScan = async () => {
    setScanning(true)
    setError('')
    try {
      const data = await scanSwingPicks()
      setPayload(data)
    } catch (err) {
      setError(apiError(err, 'Swing scan failed. Connect Angel One and retry.'))
    } finally {
      setScanning(false)
    }
  }

  const signals = payload?.signals || []
  const generatedAt = formatWhen(payload?.generated_at)

  return (
    <section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-800 px-4 py-3">
        <div>
          <p className="text-emerald-400 text-xs uppercase tracking-widest">Live scan</p>
          <h3 className="text-lg font-semibold text-slate-100 mt-0.5">Today&apos;s swing candidates</h3>
          <p className="text-xs text-slate-500 mt-1">
            Ranked from the Nifty 50 universe by the swing desk engine — this list changes with the market.
          </p>
        </div>
        <div className="flex flex-col items-stretch sm:items-end gap-1">
          <button
            type="button"
            onClick={runScan}
            disabled={scanning}
            className="inline-flex min-h-[40px] items-center justify-center rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {scanning ? 'Scanning Nifty 50…' : 'Run fresh scan'}
          </button>
          <p className="text-xs text-slate-500">
            {generatedAt ? `Scanned ${generatedAt}` : loading ? 'Loading…' : 'No scan yet'}
            {payload?.universe_size ? ` · ${payload.universe_size} stocks` : ''}
          </p>
        </div>
      </div>

      {error ? (
        <div className="border-b border-amber-500/20 bg-amber-500/5 px-4 py-3 text-sm text-amber-100">
          {error}
        </div>
      ) : null}

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-950/70 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2.5 font-medium">#</th>
              <th className="px-3 py-2.5 font-medium">Stock</th>
              <th className="px-3 py-2.5 font-medium">Setup</th>
              <th className="px-3 py-2.5 font-medium">Entry</th>
              <th className="px-3 py-2.5 font-medium">SL</th>
              <th className="px-3 py-2.5 font-medium">Target</th>
              <th className="px-3 py-2.5 font-medium">Score</th>
              <th className="px-3 py-2.5 font-medium">Conf</th>
              <th className="px-3 py-2.5 font-medium">R:R</th>
            </tr>
          </thead>
          <tbody>
            {!signals.length ? (
              <tr>
                <td colSpan={9} className="px-4 py-8 text-center text-slate-500">
                  {loading
                    ? 'Loading cached picks…'
                    : 'No live candidates cached. Run a fresh scan to rank the Nifty 50 universe.'}
                </td>
              </tr>
            ) : (
              signals.map((signal, idx) => (
                <tr
                  key={`${signal.symbol}-${signal.strategy_name}`}
                  className="border-t border-slate-800 hover:bg-slate-900/40"
                >
                  <td className="px-3 py-3 font-medium text-emerald-300">{idx + 1}</td>
                  <td className="px-3 py-3">
                    <div className="font-medium text-slate-100">{signal.symbol}</div>
                    <div className="text-xs text-slate-500">{signal.side}</div>
                  </td>
                  <td className="px-3 py-3 text-slate-300">
                    {signal.metadata?.strategy_code || signal.strategy_name}
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap">{formatInr(signal.entry)}</td>
                  <td className="px-3 py-3 whitespace-nowrap text-rose-300">{formatInr(signal.stoploss)}</td>
                  <td className="px-3 py-3 whitespace-nowrap text-emerald-300">
                    {formatInr(signal.targets?.[0])}
                  </td>
                  <td className="px-3 py-3 text-slate-300">{signal.score ?? '—'}</td>
                  <td className="px-3 py-3">
                    <ConfPill value={signal.confidence} />
                  </td>
                  <td className="px-3 py-3 text-slate-300">
                    {signal.risk_reward ? `1 : ${signal.risk_reward}` : '—'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <p className="border-t border-slate-800 px-4 py-2.5 text-xs text-slate-600">
        Cached picks refresh hourly; a fresh scan re-ranks the universe on demand and can take a minute or two.
      </p>
    </section>
  )
}
