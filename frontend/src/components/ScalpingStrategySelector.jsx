import { filterStrategiesForDesk } from '../utils/strategyFilters'

const FAMILY_LABELS = {
  battle: 'Battle',
  adaptive: 'Adaptive',
  smc: 'SMC',
}

/** Enable/disable scalping strategies · saved with desk config. */
export default function ScalpingStrategySelector({
  instrument,
  strategies = [],
  settings = {},
  mode = 'auto',
  fixedCode,
  onSettingsChange,
  onFixedChange,
  compact = false,
}) {
  const list = filterStrategiesForDesk('scalping', strategies).filter(
    (s) => !s.instruments || s.instruments.includes(instrument)
  )

  if (!list.length) {
    return (
      <p className="text-xs text-slate-500 mb-4">Loading strategies…</p>
    )
  }

  const updateStrategy = (code, patch) => {
    const next = { ...settings, [code]: { ...(settings[code] || {}), ...patch } }
    onSettingsChange?.(next)
  }

  const enabledList = list.filter((s) => {
    const sCfg = settings[s.code] || {}
    return sCfg.enabled ?? s.enabled ?? true
  })

  const inner = (
    <>
      <p className="text-xs text-slate-500 mb-3">
        {mode === 'auto'
          ? 'AI picks the best enabled strategy each bar.'
          : 'Manual mode uses one fixed strategy below.'}
      </p>
      <div className="space-y-2">
        {list.map((s) => {
          const sCfg = settings[s.code] || { enabled: s.enabled ?? true, execution_mode: 'paper' }
          return (
            <label
              key={s.code}
              className="flex items-start gap-3 rounded-lg border border-slate-800/80 bg-slate-950/30 p-2.5 cursor-pointer hover:border-amber-500/30"
            >
              <input
                type="checkbox"
                checked={Boolean(sCfg.enabled ?? s.enabled ?? true)}
                onChange={(e) => updateStrategy(s.code, { enabled: e.target.checked })}
                className="mt-0.5 accent-amber-500"
              />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-amber-300">{s.code}</span>
                  <span className="text-[10px] text-slate-500">
                    {FAMILY_LABELS[s.family] || s.family}
                  </span>
                </span>
                <span className="block text-sm font-medium text-slate-200">{s.label}</span>
                {s.description && (
                  <span className="block text-xs text-slate-500 mt-0.5 line-clamp-2">{s.description}</span>
                )}
              </span>
              <div className="flex gap-1 shrink-0">
                {['paper', 'live'].map((m) => (
                  <button
                    key={m}
                    type="button"
                    disabled={!(sCfg.enabled ?? s.enabled ?? true)}
                    onClick={(e) => {
                      e.preventDefault()
                      updateStrategy(s.code, { execution_mode: m })
                    }}
                    className={`rounded px-1.5 py-0.5 text-[10px] capitalize ${
                      !(sCfg.enabled ?? s.enabled ?? true)
                        ? 'opacity-30 border border-slate-800 text-slate-600'
                        : sCfg.execution_mode === m
                          ? m === 'paper'
                            ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                            : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                          : 'border border-slate-700 text-slate-500'
                    }`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </label>
          )
        })}
      </div>

      {mode === 'manual' && enabledList.length > 0 && (
        <label className="block text-sm mt-3">
          <span className="text-slate-400 text-xs">Fixed strategy (manual mode)</span>
          <select
            value={fixedCode || enabledList[0]?.code}
            onChange={(e) => {
              const code = e.target.value
              const picked = list.find((s) => s.code === code)
              onFixedChange?.(code, picked)
            }}
            className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm"
          >
            {enabledList.map((s) => (
              <option key={s.code} value={s.code}>
                {s.code} — {s.label}
              </option>
            ))}
          </select>
        </label>
      )}
    </>
  )

  if (compact) {
    return (
      <div className="mb-4 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
        <p className="text-amber-400 text-xs uppercase tracking-widest mb-1">Strategies</p>
        {inner}
      </div>
    )
  }

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 mb-4">
      <p className="text-amber-400 text-xs uppercase tracking-widest">Strategies</p>
      <h3 className="font-semibold mt-1 mb-3">Scalping modules</h3>
      {inner}
    </section>
  )
}
