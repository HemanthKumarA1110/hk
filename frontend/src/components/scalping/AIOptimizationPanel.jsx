/** AI optimization suggestions after backtest. */
export default function AIOptimizationPanel({ optimization, onApply, strategyVersion }) {
  if (!optimization) return null
  return (
    <section className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-cyan-400 text-xs uppercase tracking-widest">AI Optimization</p>
          <h3 className="font-semibold">Strategy v{strategyVersion} → v{optimization.strategy_version}</h3>
        </div>
        <button type="button" onClick={onApply} className="rounded-lg bg-cyan-500 text-slate-950 px-4 py-2 text-sm font-semibold">
          Apply AI Suggestions
        </button>
      </div>
      <p className="text-sm text-slate-300 mb-3">{optimization.analysis}</p>
      <ul className="space-y-1 text-sm text-slate-400">
        {(optimization.suggestions || []).map((s) => (
          <li key={s}>• {s}</li>
        ))}
      </ul>
    </section>
  )
}
