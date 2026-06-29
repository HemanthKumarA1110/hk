import { useEffect, useState } from 'react'
import { fetchAIDecisions, fetchJournalInsights, runAIEvaluation } from '../api'

const ACTION_COLORS = {
  enter: 'text-emerald-400 bg-emerald-500/10',
  scale_in: 'text-cyan-400 bg-cyan-500/10',
  avoid: 'text-slate-400 bg-slate-500/10',
  exit: 'text-rose-400 bg-rose-500/10',
  partial_book: 'text-amber-400 bg-amber-500/10',
  hold: 'text-violet-400 bg-violet-500/10',
}

export default function AIReasoningPanel() {
  const [data, setData] = useState(null)
  const [insights, setInsights] = useState(null)
  const [selected, setSelected] = useState(null)
  const [busy, setBusy] = useState(false)

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
      refresh()
    } finally {
      setBusy(false)
    }
  }

  const approved = data?.approved || []
  const decisions = data?.decisions || []

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <p className="text-violet-400 text-xs uppercase tracking-widest">Phase 4</p>
          <h2 className="text-xl font-semibold">AI Decision Engine</h2>
          <p className="text-slate-500 text-sm mt-1">
            Enter threshold 75 · Adaptive weights active
          </p>
        </div>
        <button
          type="button"
          onClick={handleRun}
          disabled={busy}
          className="rounded-lg bg-violet-500 hover:bg-violet-400 text-slate-950 px-4 py-2 text-sm font-semibold"
        >
          {busy ? 'Evaluating...' : 'Evaluate Now'}
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-3 mb-4">
        <Stat label="Approved Trades" value={approved.length} />
        <Stat label="Rejected" value={data?.rejected_count ?? 0} />
        <Stat label="Journal Win Rate" value={insights ? `${(insights.win_rate * 100).toFixed(0)}%` : '—'} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="font-medium mb-2">AI Approved Signals</h3>
          <div className="space-y-2 max-h-80 overflow-auto">
            {approved.length === 0 && <p className="text-sm text-slate-500">No trades above AI threshold yet.</p>}
            {approved.map((d) => (
              <button
                key={`${d.symbol}-${d.action}`}
                type="button"
                onClick={() => setSelected(d)}
                className="w-full text-left border border-slate-800 rounded-lg p-3 hover:bg-slate-950/50"
              >
                <div className="flex justify-between items-center">
                  <span className="font-medium">{d.symbol}</span>
                  <span className={`text-xs px-2 py-0.5 rounded ${ACTION_COLORS[d.action] || ACTION_COLORS.avoid}`}>
                    {d.action.toUpperCase()}
                  </span>
                </div>
                <div className="flex justify-between text-sm text-slate-400 mt-1">
                  <span>Score {d.score.toFixed(0)}</span>
                  <span>{d.regime.replace(/_/g, ' ')}</span>
                </div>
              </button>
            ))}
          </div>
        </div>

        <div>
          <h3 className="font-medium mb-2">Why This Trade?</h3>
          {!selected && <p className="text-sm text-slate-500">Select an approved signal to see AI reasoning.</p>}
          {selected && (
            <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3 text-sm space-y-2 max-h-80 overflow-auto">
              {selected.reasoning?.map((line, idx) => (
                <p key={idx} className="text-slate-300 leading-relaxed">{line}</p>
              ))}
            </div>
          )}

          {insights?.insights && (
            <div className="mt-4 pt-4 border-t border-slate-800">
              <h4 className="text-sm font-medium mb-2">Journal Insights</h4>
              <ul className="text-xs text-slate-400 space-y-1">
                {insights.insights.map((line, idx) => (
                  <li key={idx}>• {line}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

function Stat({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-800 p-3">
      <p className="text-xs text-slate-500 uppercase">{label}</p>
      <p className="text-xl font-semibold mt-1">{value}</p>
    </div>
  )
}
