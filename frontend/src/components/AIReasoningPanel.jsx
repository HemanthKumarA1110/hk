import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchAIDecisions, fetchJournalInsights, runAIEvaluation } from '../api'

const ACTION_META = {
  enter: { label: 'ENTER', className: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' },
  scale_in: { label: 'SCALE IN', className: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/30' },
  avoid: { label: 'AVOID', className: 'text-slate-400 bg-slate-500/10 border-slate-500/30' },
  exit: { label: 'EXIT', className: 'text-rose-400 bg-rose-500/10 border-rose-500/30' },
  partial_book: { label: 'PARTIAL', className: 'text-amber-400 bg-amber-500/10 border-amber-500/30' },
  hold: { label: 'HOLD', className: 'text-violet-400 bg-violet-500/10 border-violet-500/30' },
}

const FILTER_TABS = [
  { id: 'all', label: 'All signals' },
  { id: 'go', label: 'Go (enter)' },
  { id: 'skip', label: 'Skip (avoid)' },
  { id: 'manage', label: 'Manage (exit/hold)' },
]

const ENGINE_STYLE = {
  scalping: 'text-amber-300',
  intraday: 'text-cyan-300',
  swing: 'text-violet-300',
}

function matchesFilter(decision, filter) {
  const action = (decision.action || '').toLowerCase()
  if (filter === 'go') return action === 'enter' || action === 'scale_in'
  if (filter === 'skip') return action === 'avoid'
  if (filter === 'manage') return action === 'exit' || action === 'hold' || action === 'partial_book'
  return true
}

function formatTime(iso) {
  if (!iso) return 'Never'
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

export default function AIReasoningPanel({ compact = false }) {
  const [data, setData] = useState(null)
  const [insights, setInsights] = useState(null)
  const [selected, setSelected] = useState(null)
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState('all')

  const refresh = () => {
    fetchAIDecisions().then(setData).catch(() => null)
    fetchJournalInsights().then(setInsights).catch(() => null)
  }

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 30000)
    return () => clearInterval(timer)
  }, [])

  const handleRun = async () => {
    setBusy(true)
    try {
      const result = await runAIEvaluation()
      setData(result)
      if (result?.approved?.length) {
        setSelected(result.approved[0])
      } else if (result?.decisions?.length) {
        setSelected(result.decisions[0])
      }
      fetchJournalInsights().then(setInsights).catch(() => null)
    } finally {
      setBusy(false)
    }
  }

  const decisions = data?.decisions || []
  const filtered = useMemo(
    () => decisions.filter((d) => matchesFilter(d, filter)),
    [decisions, filter]
  )

  const approvedCount = decisions.filter((d) =>
    ['enter', 'scale_in'].includes((d.action || '').toLowerCase())
  ).length
  const rejectedCount = data?.rejected_count ?? decisions.filter((d) => d.action === 'avoid').length

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      {!compact && (
        <div className="rounded-lg border border-violet-500/20 bg-violet-500/5 p-4 mb-4 text-sm text-slate-400">
          <p className="text-violet-300 font-medium mb-1">What this shows</p>
          <p>
            The AI scores every live strategy signal (scalping, intraday, swing) and recommends{' '}
            <span className="text-emerald-400">ENTER</span>, <span className="text-slate-300">AVOID</span>, or{' '}
            <span className="text-rose-400">EXIT</span>. Use it before enabling auto-trading, or to understand
            why a signal was blocked. Desk-level entry filters and dynamic exits run separately on each bot —
            see the <Link to="/strategy" className="text-violet-300 hover:underline">Strategy → AI layer</Link> tab
            for that detail.
          </p>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          {!compact && (
            <p className="text-violet-400 text-xs uppercase tracking-widest">Signal scoring</p>
          )}
          <h2 className={`font-semibold ${compact ? 'text-xl' : 'text-xl'}`}>
            {compact ? 'AI Signal Scores' : 'Live AI decisions'}
          </h2>
          <p className="text-slate-500 text-sm mt-1">
            Last run: {formatTime(data?.generated_at)}
            {data?.weights ? ' · adaptive weights active' : ''}
          </p>
        </div>
        <button
          type="button"
          onClick={handleRun}
          disabled={busy}
          className="rounded-lg bg-violet-500 hover:bg-violet-400 text-slate-950 px-4 py-2 text-sm font-semibold disabled:opacity-50"
        >
          {busy ? 'Scoring signals…' : 'Score signals now'}
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-3 mb-4">
        <Stat label="Go (enter)" value={approvedCount} tone="good" />
        <Stat label="Skip (avoid)" value={rejectedCount} />
        <Stat
          label="Journal win rate"
          value={insights ? `${(insights.win_rate * 100).toFixed(0)}%` : '—'}
        />
      </div>

      {decisions.length === 0 && !busy && (
        <div className="rounded-lg border border-dashed border-slate-700 p-6 mb-4 text-center text-sm text-slate-500">
          <p>No AI scores yet.</p>
          <p className="mt-2">
            Run <Link to="/strategy" className="text-violet-300 hover:underline">Strategy engines</Link> first,
            then click <strong className="text-slate-300">Score signals now</strong>.
          </p>
        </div>
      )}

      <div className="flex flex-wrap gap-2 mb-3">
        {FILTER_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setFilter(tab.id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
              filter === tab.id
                ? 'border-violet-500/50 bg-violet-500/10 text-violet-300'
                : 'border-slate-800 text-slate-500 hover:text-slate-300'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="font-medium mb-2 text-sm text-slate-400 uppercase tracking-wider">
            Signals ({filtered.length})
          </h3>
          <div className="space-y-2 max-h-96 overflow-auto">
            {filtered.length === 0 && (
              <p className="text-sm text-slate-500">No signals in this filter.</p>
            )}
            {filtered.map((d) => {
              const meta = ACTION_META[d.action] || ACTION_META.avoid
              const isSelected =
                selected?.symbol === d.symbol &&
                selected?.action === d.action &&
                selected?.engine === d.engine
              return (
                <button
                  key={`${d.engine}-${d.symbol}-${d.action}`}
                  type="button"
                  onClick={() => setSelected(d)}
                  className={`w-full text-left border rounded-lg p-3 transition-colors ${
                    isSelected
                      ? 'border-violet-500/50 bg-violet-500/5'
                      : 'border-slate-800 hover:bg-slate-950/50'
                  }`}
                >
                  <div className="flex justify-between items-start gap-2">
                    <div>
                      <span className="font-medium font-mono text-sm">{d.symbol}</span>
                      <p className={`text-xs mt-0.5 capitalize ${ENGINE_STYLE[d.engine] || 'text-slate-500'}`}>
                        {d.engine}
                      </p>
                    </div>
                    <span className={`text-[10px] px-2 py-0.5 rounded border ${meta.className}`}>
                      {meta.label}
                    </span>
                  </div>
                  <div className="flex justify-between items-center text-sm text-slate-400 mt-2">
                    <span>
                      Score <span className="text-slate-200 font-mono">{d.score?.toFixed?.(0) ?? d.score}</span>
                      <span className="text-slate-600"> / {d.threshold ?? 75}</span>
                    </span>
                    <span className="text-xs capitalize">{(d.regime || '').replace(/_/g, ' ')}</span>
                  </div>
                  <div className="mt-2 h-1 rounded-full bg-slate-800 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        d.score >= (d.threshold || 75) ? 'bg-emerald-500' : 'bg-slate-600'
                      }`}
                      style={{ width: `${Math.min(100, Math.max(0, d.score || 0))}%` }}
                    />
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        <div>
          <h3 className="font-medium mb-2 text-sm text-slate-400 uppercase tracking-wider">
            Reasoning
          </h3>
          {!selected && (
            <p className="text-sm text-slate-500">
              Select a signal to see why the AI chose that action.
            </p>
          )}
          {selected && (
            <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4 text-sm space-y-3 max-h-96 overflow-auto">
              <div className="flex flex-wrap gap-2 text-xs">
                <span className="font-mono text-slate-200">{selected.symbol}</span>
                <span className="capitalize text-slate-500">{selected.engine}</span>
                <span className={`px-2 py-0.5 rounded border ${(ACTION_META[selected.action] || ACTION_META.avoid).className}`}>
                  {(ACTION_META[selected.action] || ACTION_META.avoid).label}
                </span>
              </div>
              <p className="text-slate-500 text-xs">
                Confidence{' '}
                {selected.confidence != null
                  ? `${(selected.confidence * 100).toFixed(0)}%`
                  : '—'}{' '}
                · Size {selected.recommended_size_pct ?? 100}%
              </p>
              <div className="space-y-2">
                {(selected.reasoning || []).map((line, idx) => (
                  <p key={idx} className="text-slate-300 leading-relaxed">
                    {line}
                  </p>
                ))}
                {!selected.reasoning?.length && (
                  <p className="text-slate-500">No reasoning lines recorded for this signal.</p>
                )}
              </div>
              {selected.features && Object.keys(selected.features).length > 0 && (
                <div className="pt-3 border-t border-slate-800">
                  <p className="text-xs text-slate-500 uppercase mb-2">Feature scores</p>
                  <div className="grid grid-cols-2 gap-2">
                    {Object.entries(selected.features)
                      .filter(([, v]) => v != null)
                      .slice(0, 8)
                      .map(([key, value]) => (
                        <div key={key} className="text-xs">
                          <div className="flex justify-between text-slate-500 capitalize">
                            <span>{key.replace(/_/g, ' ')}</span>
                            <span className="font-mono text-slate-300">{Number(value).toFixed(0)}</span>
                          </div>
                          <div className="h-1 mt-1 rounded-full bg-slate-800">
                            <div
                              className="h-full rounded-full bg-violet-500/70"
                              style={{ width: `${Math.min(100, Number(value))}%` }}
                            />
                          </div>
                        </div>
                      ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {insights?.insights && !compact && (
            <div className="mt-4 pt-4 border-t border-slate-800">
              <h4 className="text-sm font-medium mb-2">From your journal</h4>
              <ul className="text-xs text-slate-400 space-y-1">
                {insights.insights.slice(0, 3).map((line, idx) => (
                  <li key={idx}>• {line}</li>
                ))}
              </ul>
              <Link to="/journal" className="inline-block mt-2 text-xs text-violet-300 hover:underline">
                Open trade journal →
              </Link>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

function Stat({ label, value, tone }) {
  const toneClass =
    tone === 'good' ? 'text-emerald-400' : tone === 'bad' ? 'text-rose-400' : 'text-slate-100'
  return (
    <div className="rounded-lg border border-slate-800 p-3">
      <p className="text-xs text-slate-500 uppercase">{label}</p>
      <p className={`text-xl font-semibold mt-1 ${toneClass}`}>{value}</p>
    </div>
  )
}
