import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  fetchBacktestRun,
  fetchBacktestRuns,
  fetchIntradayStrategies,
  fetchScalpingStrategies,
  fetchSwingStrategies,
} from '../api'
import DeskBacktestModule from '../components/DeskBacktestModule'
import EquityCurveChart from '../components/EquityCurveChart'
import MetricCard from '../components/MetricCard'
import BacktestModule from '../components/scalping/BacktestModule'
import { useBacktest } from '../hooks/useBacktest'
import { useDeskBacktest } from '../hooks/useDeskBacktest'

const TABS = [
  { id: 'scalping', label: 'Scalping' },
  { id: 'intraday', label: 'Intraday' },
  { id: 'swing', label: 'Swing' },
  { id: 'history', label: 'Run history' },
]

const DESK_LINKS = [
  { to: '/scalping/nifty50', label: 'Nifty desk', desc: 'Charts · live bot' },
  { to: '/scalping/banknifty', label: 'Bank Nifty desk', desc: 'Charts · live bot' },
  { to: '/intraday', label: 'Intraday desk', desc: 'Scan · auto bot' },
  { to: '/swing', label: 'Swing desk', desc: 'Daily scan · portfolio' },
  { to: '/strategy', label: 'Strategy catalog', desc: 'All SCALP / INTRA / SWING codes' },
]

export default function BacktestPage() {
  const [tab, setTab] = useState('scalping')
  const [intradayStrategies, setIntradayStrategies] = useState([])
  const [swingStrategies, setSwingStrategies] = useState([])
  const [niftyStrategies, setNiftyStrategies] = useState([])
  const [bankStrategies, setBankStrategies] = useState([])
  const [history, setHistory] = useState([])
  const [historyRun, setHistoryRun] = useState(null)
  const [historyBusy, setHistoryBusy] = useState(false)

  const niftyBacktest = useBacktest('nifty50')
  const bankBacktest = useBacktest('banknifty')
  const intradayBacktest = useDeskBacktest('intraday')
  const swingBacktest = useDeskBacktest('swing')

  useEffect(() => {
    fetchIntradayStrategies()
      .then((d) => setIntradayStrategies(d?.strategies || []))
      .catch(() => setIntradayStrategies([]))
    fetchSwingStrategies()
      .then((d) => setSwingStrategies(d?.strategies || []))
      .catch(() => setSwingStrategies([]))
    fetchScalpingStrategies('nifty50')
      .then((d) => setNiftyStrategies(d?.strategies || []))
      .catch(() => setNiftyStrategies([]))
    fetchScalpingStrategies('banknifty')
      .then((d) => setBankStrategies(d?.strategies || []))
      .catch(() => setBankStrategies([]))
    fetchBacktestRuns()
      .then(setHistory)
      .catch(() => setHistory([]))
  }, [])

  const loadHistoryRun = async (runId) => {
    setHistoryBusy(true)
    try {
      const data = await fetchBacktestRun(runId)
      setHistoryRun(data)
    } finally {
      setHistoryBusy(false)
    }
  }

  const historyMetrics = historyRun?.metrics
  const historyCurve = (historyRun?.equity_curve || []).map((equity, i) => ({
    date: `#${i + 1}`,
    equity,
  }))

  return (
    <div>
      <header className="mb-6">
        <p className="text-orange-400 text-xs uppercase tracking-widest">Backtesting</p>
        <h2 className="text-3xl font-bold mt-1">Strategy Validation Hub</h2>
        <p className="text-slate-400 mt-1 max-w-3xl">
          60-day evaluation window across all desks. Toggle AI entry/exit to compare against baseline
          strategy logic — battle-tested scalps keep strategy exits; AI mainly filters entries and cuts
          losers on adaptive modules.{' '}
          <Link to="/backtest/results" className="text-orange-300 hover:underline">
            View all past results →
          </Link>
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5 mb-6">
        {DESK_LINKS.map((link) => (
          <Link
            key={link.to}
            to={link.to}
            className="rounded-lg border border-slate-800 bg-slate-900/40 p-3 hover:border-slate-600 transition-colors"
          >
            <p className="text-sm font-medium text-slate-200">{link.label}</p>
            <p className="text-xs text-slate-500 mt-0.5">{link.desc}</p>
          </Link>
        ))}
      </div>

      <div className="flex flex-wrap gap-2 mb-6 border-b border-slate-800 pb-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg -mb-px border-b-2 transition-colors ${
              tab === t.id
                ? 'border-orange-400 text-orange-300'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'scalping' && (
        <div className="space-y-6">
          <section className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4 text-sm text-slate-400">
            <p className="text-amber-400 font-medium mb-1">Scalping · SCALP-* catalog</p>
            <p>
              Index options backtest on Angel One 1m candles (max 60 days). Nifty 50 and Bank Nifty run
              independently — pick a strategy per instrument.
            </p>
          </section>
          <BacktestModule
            instrument="nifty50"
            backtest={niftyBacktest}
            onRun={(form) => niftyBacktest.run(form)}
            strategies={niftyStrategies}
            defaultOpen
          />
          <BacktestModule
            instrument="banknifty"
            backtest={bankBacktest}
            onRun={(form) => bankBacktest.run(form)}
            strategies={bankStrategies}
            defaultOpen
          />
        </div>
      )}

      {tab === 'intraday' && (
        <div className="space-y-4">
          <section className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-4 text-sm text-slate-400">
            <p className="text-cyan-400 font-medium mb-1">Intraday · INTRA-* catalog</p>
            <p>
              Auto-picks top Nifty 50 names by screen score, then backtests each with split capital.
              Uncheck demo data when Angel One is connected for real 5m history.
            </p>
          </section>
          <DeskBacktestModule
            engine="intraday"
            accent="cyan"
            title="Intraday Strategy Backtest"
            defaultInterval="5m"
            strategies={intradayStrategies}
            backtest={intradayBacktest}
            defaultOpen
          />
        </div>
      )}

      {tab === 'swing' && (
        <div className="space-y-4">
          <section className="rounded-xl border border-violet-500/20 bg-violet-500/5 p-4 text-sm text-slate-400">
            <p className="text-violet-400 font-medium mb-1">Swing · SWING-* catalog</p>
            <p>
              Portfolio backtest on top 15 Nifty 50 picks with delivery costs, max concurrent positions,
              and ~14 months of daily bars for EMA200 warmup (60-day eval window).
            </p>
          </section>
          <DeskBacktestModule
            engine="swing"
            accent="violet"
            title="Swing Portfolio Backtest"
            defaultInterval="1d"
            strategies={swingStrategies}
            backtest={swingBacktest}
            defaultOpen
          />
        </div>
      )}

      {tab === 'history' && (
        <div className="grid gap-6 lg:grid-cols-3">
          <section className="lg:col-span-1 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold">Recent runs</h3>
              <button
                type="button"
                onClick={() => fetchBacktestRuns().then(setHistory).catch(() => null)}
                className="text-xs text-orange-400 hover:text-orange-300"
              >
                Refresh
              </button>
            </div>
            <div className="space-y-2 max-h-[32rem] overflow-auto">
              {history.length === 0 && <p className="text-sm text-slate-500">No runs yet.</p>}
              {history.map((run) => (
                <button
                  key={run.run_id}
                  type="button"
                  onClick={() => loadHistoryRun(run.run_id)}
                  className={`w-full text-left border rounded-lg p-2 hover:bg-slate-950/50 text-sm ${
                    historyRun?.run_id === run.run_id
                      ? 'border-orange-500/50 bg-slate-950/40'
                      : 'border-slate-800'
                  }`}
                >
                  <div className="flex justify-between gap-2">
                    <span className="capitalize">{run.engine}</span>
                    <span className={run.status === 'completed' ? 'text-emerald-400' : 'text-slate-500'}>
                      {run.status}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 mt-1">{run.symbol}</p>
                  <p className="text-xs text-slate-500">{run.from_date} → {run.to_date}</p>
                </button>
              ))}
            </div>
          </section>

          <section className="lg:col-span-2 rounded-xl border border-slate-800 bg-slate-900/60 p-4 min-h-[20rem]">
            {!historyRun && !historyBusy && (
              <p className="text-sm text-slate-500">Select a run to view metrics and trades.</p>
            )}
            {historyBusy && <p className="text-sm text-slate-400">Loading…</p>}
            {historyRun && (
              <>
                <div className="flex flex-wrap items-center gap-2 mb-4">
                  <h3 className="font-semibold capitalize">{historyRun.engine} backtest</h3>
                  <span className="text-xs text-slate-500">{historyRun.symbol}</span>
                  {historyMetrics?.ai_entry && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400">
                      AI entry
                    </span>
                  )}
                  {historyMetrics?.ai_exit && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400">
                      AI exit
                    </span>
                  )}
                </div>
                <div className="grid gap-4 md:grid-cols-4 mb-4">
                  <MetricCard label="Status" value={historyRun.status} />
                  <MetricCard label="Data source" value={historyRun.data_source || '—'} />
                  <MetricCard label="Trades" value={historyMetrics?.total_trades ?? '—'} />
                  <MetricCard label="Win rate" value={historyMetrics ? `${historyMetrics.win_rate}%` : '—'} />
                </div>
                {historyMetrics && (
                  <div className="grid gap-4 md:grid-cols-4 mb-4">
                    <MetricCard
                      label="Final capital"
                      value={`₹${Number(historyMetrics.final_capital || 0).toLocaleString('en-IN')}`}
                      tone={(historyMetrics.total_pnl || 0) >= 0 ? 'good' : 'bad'}
                    />
                    <MetricCard
                      label="Total P&L"
                      value={`₹${Number(historyMetrics.total_pnl || 0).toLocaleString('en-IN')}`}
                    />
                    <MetricCard label="Max drawdown" value={`${historyMetrics.max_drawdown}%`} tone="warn" />
                    <MetricCard label="Profit factor" value={historyMetrics.profit_factor ?? '—'} />
                  </div>
                )}
                {historyRun.error_message && (
                  <p className="text-rose-400 text-sm mb-4">{historyRun.error_message}</p>
                )}
                {historyCurve.length > 1 && (
                  <div className="mb-4">
                    <EquityCurveChart points={historyCurve} />
                  </div>
                )}
                {historyRun.trades?.length > 0 && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="text-slate-500 text-xs uppercase">
                        <tr>
                          <th className="text-left p-2">Symbol</th>
                          <th className="text-left p-2">Side</th>
                          <th className="text-right p-2">Entry</th>
                          <th className="text-right p-2">Exit</th>
                          <th className="text-right p-2">P&L</th>
                        </tr>
                      </thead>
                      <tbody>
                        {historyRun.trades.slice(0, 50).map((t, idx) => (
                          <tr key={idx} className="border-t border-slate-800">
                            <td className="p-2 font-mono text-xs">{t.symbol}</td>
                            <td className="p-2">{t.side}</td>
                            <td className="p-2 text-right font-mono">{t.entry_price}</td>
                            <td className="p-2 text-right font-mono">{t.exit_price}</td>
                            <td
                              className={`p-2 text-right font-mono ${
                                t.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'
                              }`}
                            >
                              ₹{Number(t.pnl).toLocaleString('en-IN')}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {historyRun.trades.length > 50 && (
                      <p className="text-xs text-slate-500 mt-2">
                        Showing first 50 of {historyRun.trades.length} trades.
                      </p>
                    )}
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
