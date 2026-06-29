import { useEffect, useRef, useState } from 'react'
import {
  fetchBacktestPreview,
  fetchBacktestRun,
  fetchBacktestRuns,
  runBacktest,
} from '../api'
import EquityCurveChart from '../components/EquityCurveChart'
import MetricCard from '../components/MetricCard'

const ENGINES = ['scalping', 'intraday', 'swing']
const INTERVALS = ['1m', '3m', '5m', '15m', '1d']

const DEFAULT_FORM = {
  engine: 'intraday',
  symbol: 'SBIN-EQ',
  interval: '5m',
  from_date: '2025-01-01',
  to_date: '2025-03-01',
  initial_capital: 100000,
  risk_pct: 1,
  use_demo_data: true,
}

export default function BacktestPage() {
  const [preview, setPreview] = useState(null)
  const [form, setForm] = useState(DEFAULT_FORM)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [history, setHistory] = useState([])
  const pollRef = useRef(null)

  useEffect(() => {
    fetchBacktestPreview().then(setPreview).catch(() => null)
    fetchBacktestRuns().then(setHistory).catch(() => null)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const pollRun = (runId) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const data = await fetchBacktestRun(runId)
        setResult(data)
        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(pollRef.current)
          fetchBacktestRuns().then(setHistory).catch(() => null)
        }
      } catch {
        clearInterval(pollRef.current)
      }
    }, 2000)
  }

  const handleRun = async () => {
    setBusy(true)
    setResult(null)
    try {
      const created = await runBacktest(form)
      if (created.status === 'completed') {
        const data = await fetchBacktestRun(created.run_id)
        setResult(data)
        fetchBacktestRuns().then(setHistory).catch(() => null)
      } else {
        setResult({ run_id: created.run_id, status: 'pending' })
        pollRun(created.run_id)
      }
    } finally {
      setBusy(false)
    }
  }

  const loadRun = async (runId) => {
    const data = await fetchBacktestRun(runId)
    setResult(data)
  }

  const metrics = result?.metrics
  const curvePoints = (result?.equity_curve || []).map((equity, i) => ({
    date: `#${i + 1}`,
    equity,
  }))

  return (
    <div>
      <header className="mb-6">
        <p className="text-orange-400 text-xs uppercase tracking-widest">Backtesting</p>
        <h2 className="text-3xl font-bold mt-1">Strategy Validation</h2>
        <p className="text-slate-400 mt-1">
          {preview?.message || 'Replay production engines on historical OHLCV'}
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-3 mb-6">
        <section className="lg:col-span-2 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h3 className="font-semibold mb-4">Run Configuration</h3>
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Engine">
              <select
                value={form.engine}
                onChange={(e) => setForm({ ...form, engine: e.target.value })}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              >
                {ENGINES.map((e) => (
                  <option key={e} value={e}>{e}</option>
                ))}
              </select>
            </Field>
            <Field label="Symbol">
              <input
                value={form.symbol}
                onChange={(e) => setForm({ ...form, symbol: e.target.value })}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              />
            </Field>
            <Field label="Interval">
              <select
                value={form.interval}
                onChange={(e) => setForm({ ...form, interval: e.target.value })}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              >
                {INTERVALS.map((i) => (
                  <option key={i} value={i}>{i}</option>
                ))}
              </select>
            </Field>
            <Field label="Initial Capital">
              <input
                type="number"
                value={form.initial_capital}
                onChange={(e) => setForm({ ...form, initial_capital: Number(e.target.value) })}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              />
            </Field>
            <Field label="From Date">
              <input
                type="date"
                value={form.from_date}
                onChange={(e) => setForm({ ...form, from_date: e.target.value })}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              />
            </Field>
            <Field label="To Date">
              <input
                type="date"
                value={form.to_date}
                onChange={(e) => setForm({ ...form, to_date: e.target.value })}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              />
            </Field>
          </div>
          <label className="flex items-center gap-2 mt-3 text-sm text-slate-400">
            <input
              type="checkbox"
              checked={form.use_demo_data}
              onChange={(e) => setForm({ ...form, use_demo_data: e.target.checked })}
            />
            Use demo synthetic data (no broker required)
          </label>
          <button
            type="button"
            onClick={handleRun}
            disabled={busy}
            className="mt-4 rounded-lg bg-orange-500 hover:bg-orange-400 text-slate-950 px-4 py-2 text-sm font-semibold"
          >
            {busy ? 'Starting...' : 'Run Backtest'}
          </button>
        </section>

        <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h3 className="font-semibold mb-3">Recent Runs</h3>
          <div className="space-y-2 max-h-80 overflow-auto">
            {history.length === 0 && <p className="text-sm text-slate-500">No runs yet.</p>}
            {history.map((run) => (
              <button
                key={run.run_id}
                type="button"
                onClick={() => loadRun(run.run_id)}
                className="w-full text-left border border-slate-800 rounded-lg p-2 hover:bg-slate-950/50 text-sm"
              >
                <div className="flex justify-between">
                  <span>{run.engine} · {run.symbol}</span>
                  <span className={run.status === 'completed' ? 'text-emerald-400' : 'text-slate-500'}>
                    {run.status}
                  </span>
                </div>
                <p className="text-xs text-slate-500 mt-1">{run.from_date} → {run.to_date}</p>
              </button>
            ))}
          </div>
        </section>
      </div>

      {result && (
        <>
          <div className="grid gap-4 md:grid-cols-4 mb-6">
            <MetricCard label="Status" value={result.status} />
            <MetricCard label="Data Source" value={result.data_source || '—'} />
            <MetricCard
              label="Total Trades"
              value={metrics?.total_trades ?? '—'}
            />
            <MetricCard
              label="Win Rate"
              value={metrics ? `${metrics.win_rate}%` : '—'}
            />
          </div>

          {metrics && (
            <div className="grid gap-4 md:grid-cols-4 mb-6">
              <MetricCard
                label="Final Capital"
                value={`₹${Number(metrics.final_capital || 0).toLocaleString('en-IN')}`}
                tone={(metrics.total_pnl || 0) >= 0 ? 'good' : 'bad'}
              />
              <MetricCard label="Total P&L" value={`₹${Number(metrics.total_pnl || 0).toLocaleString('en-IN')}`} />
              <MetricCard label="Max Drawdown" value={`${metrics.max_drawdown}%`} tone="warn" />
              <MetricCard label="Profit Factor" value={metrics.profit_factor ?? '—'} />
            </div>
          )}

          {result.error_message && (
            <p className="text-rose-400 text-sm mb-4">{result.error_message}</p>
          )}

          {curvePoints.length > 1 && (
            <div className="mb-6">
              <EquityCurveChart points={curvePoints} />
            </div>
          )}

          {result.trades?.length > 0 && (
            <section className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
              <h3 className="font-semibold p-4 border-b border-slate-800">Trades</h3>
              <table className="w-full text-sm">
                <thead className="bg-slate-950/50 text-slate-500 text-xs uppercase">
                  <tr>
                    <th className="text-left p-3">Side</th>
                    <th className="text-right p-3">Entry</th>
                    <th className="text-right p-3">Exit</th>
                    <th className="text-right p-3">Qty</th>
                    <th className="text-right p-3">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.map((t, idx) => (
                    <tr key={idx} className="border-t border-slate-800">
                      <td className="p-3">{t.side}</td>
                      <td className="p-3 text-right font-mono">{t.entry_price}</td>
                      <td className="p-3 text-right font-mono">{t.exit_price}</td>
                      <td className="p-3 text-right">{t.qty}</td>
                      <td className={`p-3 text-right font-mono ${t.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        ₹{Number(t.pnl).toLocaleString('en-IN')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function Field({ label, children }) {
  return (
    <label className="block text-sm">
      <span className="text-slate-500 text-xs uppercase">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  )
}
