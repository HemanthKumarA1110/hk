import { useState } from 'react'
import { Link } from 'react-router-dom'
import StrategyCatalogPanel from '../components/StrategyCatalogPanel'
import StrategySignalsPanel from '../components/StrategySignalsPanel'
import { runStrategies } from '../api'

function formatApiError(err) {
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join('; ')
  return err.message || 'Strategy run failed'
}

const TABS = [
  { id: 'catalog', label: 'Strategy catalog' },
  { id: 'signals', label: 'Live signals' },
  { id: 'ai', label: 'AI layer' },
]

const AI_FEATURES = [
  {
    title: 'Entry confirmation',
    desk: 'All desks',
    detail:
      'Multi-factor checklist: price action freshness, volume, index alignment, S/R in target path, ATR vs stop. Only vetoes clearly weak setups (battle-tested scalps use lighter filtering).',
  },
  {
    title: 'Dynamic exit',
    desk: 'Scalping · Intraday · Swing',
    detail:
      'Reassesses open trades for thesis invalidation. Exits underwater trades on VWAP reclaim, momentum fade, or structure break. Protects winners — lets strategy targets handle profit-taking.',
  },
  {
    title: 'Entry validator (scalping)',
    desk: 'Scalping',
    detail:
      '5-factor gate: EMA alignment, RSI band, VWAP position, volume ≥ 1.05×, session window. Score ≥ 3 = TAKE.',
  },
  {
    title: 'Regime & MTF filters',
    desk: 'Scalping',
    detail:
      'Market regime classifier adjusts targets/size. Multi-timeframe trend blocks counter-trend entries. ORB confirmation for breakout strategies.',
  },
  {
    title: 'Post-trade review',
    desk: 'All desks',
    detail:
      'After close, compares exit timing vs next 10 bars to tune future decisions (logged in loss autopsy).',
  },
]

const QUICK_LINKS = [
  { to: '/live', label: 'Live Trading hub', desc: 'Manual orders + auto bots' },
  { to: '/backtest', label: 'Backtest', desc: '60-day eval · AI vs baseline' },
  { to: '/scalping/nifty50', label: 'Nifty scalping', desc: 'Charts · desk · backtest' },
  { to: '/intraday', label: 'Intraday desk', desc: 'Scan · signals · auto bot' },
  { to: '/swing', label: 'Swing desk', desc: 'Daily scan · portfolio' },
]

export default function StrategyPage() {
  const [tab, setTab] = useState('catalog')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [refreshToken, setRefreshToken] = useState(0)

  const handleRun = async () => {
    setBusy(true)
    setError('')
    try {
      await runStrategies()
      setRefreshToken((v) => v + 1)
      setTab('signals')
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-emerald-400 text-xs uppercase tracking-widest">Strategy Engine</p>
          <h2 className="text-3xl font-bold mt-1">Strategies</h2>
          <p className="text-slate-400 mt-1 max-w-2xl">
            Scalping (Nifty & Bank Nifty options), intraday equity, and swing delivery — modular catalogs
            with AI entry/exit and manual overrides.
          </p>
        </div>
        <button
          type="button"
          onClick={handleRun}
          disabled={busy}
          className="rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 px-4 py-2 text-sm font-semibold disabled:opacity-50"
        >
          {busy ? 'Running…' : 'Run all engines'}
        </button>
      </header>

      {error && <p className="text-rose-400 text-sm mb-4">{error}</p>}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5 mb-6">
        {QUICK_LINKS.map((link) => (
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
                ? 'border-emerald-400 text-emerald-300'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'catalog' && <StrategyCatalogPanel />}

      {tab === 'signals' && <StrategySignalsPanel refreshToken={refreshToken} />}

      {tab === 'ai' && (
        <div className="space-y-4">
          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-cyan-400 text-xs uppercase tracking-widest">AI reasoning v8</p>
            <h3 className="font-semibold text-lg mt-1">How AI supports entries & exits</h3>
            <p className="text-sm text-slate-400 mt-2">
              AI does not replace strategy logic — it filters weak entries and cuts losing trades early
              while preserving high win-rate strategy exits on winners.
            </p>
          </section>
          <div className="grid gap-4 md:grid-cols-2">
            {AI_FEATURES.map((f) => (
              <div key={f.title} className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                <p className="text-xs text-emerald-400/90">{f.desk}</p>
                <h4 className="font-semibold mt-1">{f.title}</h4>
                <p className="text-sm text-slate-400 mt-2 leading-relaxed">{f.detail}</p>
              </div>
            ))}
          </div>
          <section className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4 text-sm text-slate-400">
            <p className="text-amber-400 font-medium mb-2">Backtest note</p>
            <p>
              AI entry+exit is compared against baseline in backtests. Battle-tested scalping (
              <span className="font-mono text-slate-300">SCALP-BT-*</span>) keeps strategy exits; AI exit
              only applies to adaptive modules. Use the Backtest page with AI toggles to compare win rates.
            </p>
          </section>
        </div>
      )}
    </div>
  )
}
