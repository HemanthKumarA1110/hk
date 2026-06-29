export default function MetricCard({ label, value, sub, tone = 'default' }) {
  const tones = {
    default: 'text-slate-100',
    good: 'text-emerald-400',
    bad: 'text-rose-400',
    warn: 'text-amber-400',
  }
  return (
    <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`text-2xl font-bold mt-2 ${tones[tone] || tones.default}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </div>
  )
}
