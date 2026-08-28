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
  const isManual = mode === 'manual'

  if (!list.length) {
    return (
      <p className="text-xs text-slate-500 mb-4">Loading strategies…</p>
    )
  }

  const updateStrategy = (code, patch) => {
    const next = { ...settings, [code]: { ...(settings[code] || {}), ...patch } }
    onSettingsChange?.(next)
  }

  const setAllEnabled = (enabled) => {
    const next = { ...settings }
    list.forEach((s) => {
      next[s.code] = { ...(next[s.code] || { execution_mode: 'live' }), enabled }
    })
    onSettingsChange?.(next)
  }

  const enabledList = list.filter((s) => {
    const sCfg = settings[s.code] || {}
    return sCfg.enabled ?? s.enabled ?? true
  })
  const monitorCount = isManual ? enabledList.length : list.length

  const inner = (
    <>
      <p className="text-xs text-slate-500 mb-3">
        {isManual
          ? 'Manual mode monitors only the strategies you check (one or more).'
          : 'Auto mode monitors every strategy on this desk. First valid signal enters; one trade at a time.'}
      </p>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2 text-xs text-slate-400">
        <span>
          Monitoring <span className="text-slate-200 font-medium">{monitorCount}</span>
        </span>
        {isManual && (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setAllEnabled(true)}
              className="rounded border border-slate-700 px-2 py-0.5 text-slate-300"
            >
              Select all
            </button>
            <button
              type="button"
              onClick={() => setAllEnabled(false)}
              className="rounded border border-slate-700 px-2 py-0.5 text-slate-300"
            >
              Clear
            </button>
          </div>
        )}
      </div>
      <div className="space-y-2">
        {list.map((s) => {
          const sCfg = settings[s.code] || { enabled: s.enabled ?? true, execution_mode: 'live' }
          const checked = Boolean(sCfg.enabled ?? s.enabled ?? true)
          const monitoring = !isManual || checked
          return (
            <label
              key={s.code}
              className={`flex items-start gap-3 rounded-lg border border-slate-800/80 bg-slate-950/30 p-2.5 ${
                isManual ? 'cursor-pointer hover:border-amber-500/30' : ''
              } ${!monitoring ? 'opacity-50' : ''}`}
            >
              {isManual ? (
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) => updateStrategy(s.code, { enabled: e.target.checked })}
                  className="mt-0.5 accent-amber-500"
                />
              ) : (
                <span className="mt-0.5 text-[10px] uppercase tracking-wide text-emerald-400/80 w-8">On</span>
              )}
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
              <span className="shrink-0 rounded px-1.5 py-0.5 text-[10px] bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                Live
              </span>
            </label>
          )
        })}
      </div>
      {isManual && enabledList.length === 0 && (
        <p className="text-[11px] text-amber-300 mt-2">Select at least one strategy to monitor.</p>
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
