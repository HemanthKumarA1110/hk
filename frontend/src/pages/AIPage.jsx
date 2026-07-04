import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import AIReasoningPanel from '../components/AIReasoningPanel'
import { fetchAIWeights, fetchJournalInsights } from '../api'

const TABS = [
  { id: 'live', label: 'Live scores' },
  { id: 'learning', label: 'Adaptive learning' },
  { id: 'guide', label: 'How it works' },
]

const QUICK_LINKS = [
  { to: '/strategy', label: 'Strategy catalog', desc: 'Signals + AI layer docs' },
  { to: '/live', label: 'Live Trading', desc: 'Manual orders & auto bots' },
  { to: '/journal', label: 'Trade journal', desc: 'Outcomes feed learning' },
  { to: '/backtest', label: 'Backtest', desc: 'Compare AI vs baseline' },
]

const AI_LAYERS = [
  {
    title: 'This page — signal scorer',
    detail:
      'Scores each strategy signal (0–100) and outputs ENTER / AVOID / EXIT. Runs on cached signals from all three engines. Does not place orders by itself.',
  },
  {
    title: 'Desk entry filter',
    detail:
      'On each auto-trading bot, AI can veto weak entries (volume, RSI, VWAP, session). Battle-tested scalps use lighter gates.',
  },
  {
    title: 'Dynamic exit',
    detail:
      'While a trade is open, AI can cut losers early (VWAP reclaim, momentum fade). Winners are left to strategy targets.',
  },
  {
    title: 'Adaptive learning',
    detail:
      'Closed trades in the Journal adjust feature weights (trend, volume, risk-reward, etc.) so future scores improve over time.',
  },
]

export default function AIPage() {
  const [tab, setTab] = useState('live')
  const [weights, setWeights] = useState(null)
  const [threshold, setThreshold] = useState(75)
  const [insights, setInsights] = useState(null)

  useEffect(() => {
    fetchAIWeights()
      .then((d) => {
        setWeights(d.weights || {})
        if (d.threshold != null) setThreshold(d.threshold)
      })
      .catch(() => null)
    fetchJournalInsights().then(setInsights).catch(() => null)
  }, [tab])

  const weightEntries = Object.entries(weights || {}).sort((a, b) => b[1] - a[1])

  return (
    <div>
      <header className="mb-6">
        <p className="text-violet-400 text-xs uppercase tracking-widest">AI Monitor</p>
        <h2 className="text-3xl font-bold mt-1">Should I take this trade?</h2>
        <p className="text-slate-400 mt-1 max-w-3xl">
          Live signal scoring across scalping, intraday, and swing — plus adaptive learning from your journal.
          Use this page to review AI recommendations before auto-trading, not as a standalone strategy.
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 mb-6">
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
                ? 'border-violet-400 text-violet-300'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'live' && <AIReasoningPanel />}

      {tab === 'learning' && (
        <div className="space-y-6">
          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h3 className="font-semibold mb-2">How learning works</h3>
            <p className="text-sm text-slate-400 leading-relaxed">
              Every time you score signals, the AI reads recent{' '}
              <Link to="/journal" className="text-violet-300 hover:underline">
                journal
              </Link>{' '}
              trades and nudges feature weights up or down. Winning patterns (e.g. strong volume + trend)
              gain weight; losing patterns lose weight. Enter threshold is currently{' '}
              <span className="font-mono text-slate-200">{threshold}</span> — signals below that are marked
              AVOID.
            </p>
          </section>

          {insights && (
            <div className="grid gap-4 md:grid-cols-3">
              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs text-slate-500 uppercase">Journal trades</p>
                <p className="text-2xl font-semibold mt-1">{insights.total_trades ?? 0}</p>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs text-slate-500 uppercase">Win rate</p>
                <p className="text-2xl font-semibold mt-1">
                  {insights.win_rate != null ? `${(insights.win_rate * 100).toFixed(1)}%` : '—'}
                </p>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs text-slate-500 uppercase">Total P&L</p>
                <p className="text-2xl font-semibold mt-1">
                  ₹{Number(insights.total_pnl || 0).toLocaleString('en-IN')}
                </p>
              </div>
            </div>
          )}

          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h3 className="font-semibold mb-3">Current feature weights</h3>
            {weightEntries.length === 0 && (
              <p className="text-sm text-slate-500">Weights load after the first AI scoring run.</p>
            )}
            <div className="grid gap-3 md:grid-cols-2">
              {weightEntries.map(([key, value]) => (
                <div key={key}>
                  <div className="flex justify-between text-sm capitalize">
                    <span className="text-slate-400">{key.replace(/_/g, ' ')}</span>
                    <span className="font-mono text-violet-300">{Number(value).toFixed(2)}</span>
                  </div>
                  <div className="h-1.5 mt-1 rounded-full bg-slate-800">
                    <div
                      className="h-full rounded-full bg-violet-500"
                      style={{ width: `${Math.min(100, Number(value) * 20)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </section>

          {insights?.engine_breakdown && Object.keys(insights.engine_breakdown).length > 0 && (
            <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <h3 className="font-semibold mb-3">P&L by engine (journal)</h3>
              <div className="grid gap-2 sm:grid-cols-3">
                {Object.entries(insights.engine_breakdown).map(([engine, pnl]) => (
                  <div key={engine} className="rounded-lg border border-slate-800 p-3">
                    <p className="text-xs capitalize text-slate-500">{engine}</p>
                    <p
                      className={`font-mono font-semibold mt-1 ${
                        Number(pnl) >= 0 ? 'text-emerald-400' : 'text-rose-400'
                      }`}
                    >
                      ₹{Number(pnl).toLocaleString('en-IN')}
                    </p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {insights?.insights && (
            <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <h3 className="font-semibold mb-2">Insights</h3>
              <ul className="text-sm text-slate-400 space-y-1">
                {insights.insights.map((line) => (
                  <li key={line}>• {line}</li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}

      {tab === 'guide' && (
        <div className="space-y-4">
          <section className="rounded-xl border border-violet-500/20 bg-violet-500/5 p-4">
            <h3 className="font-semibold text-lg">When to use this page</h3>
            <ul className="mt-3 text-sm text-slate-400 space-y-2 list-disc list-inside">
              <li>Before turning on auto-trading — check which signals the AI would take</li>
              <li>After running strategy engines — click &quot;Score signals now&quot; for fresh decisions</li>
              <li>When a trade feels marginal — read the reasoning and feature scores</li>
              <li>Weekly — review the Learning tab to see if journal outcomes shifted weights</li>
            </ul>
          </section>

          <div className="grid gap-4 md:grid-cols-2">
            {AI_LAYERS.map((layer) => (
              <div key={layer.title} className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                <h4 className="font-semibold">{layer.title}</h4>
                <p className="text-sm text-slate-400 mt-2 leading-relaxed">{layer.detail}</p>
              </div>
            ))}
          </div>

          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-400">
            <p>
              Full desk-level AI documentation (entry validator, regime filters, backtest notes) lives on the{' '}
              <Link to="/strategy" className="text-violet-300 hover:underline">
                Strategy page → AI layer
              </Link>{' '}
              tab.
            </p>
          </section>
        </div>
      )}
    </div>
  )
}
