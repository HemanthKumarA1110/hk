import { useEffect, useState } from 'react'

const STORAGE_KEY = 'swing_strategy_enabled'

function loadEnabled(strategies) {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch {
    /* ignore */
  }
  return Object.fromEntries((strategies || []).map((s) => [s.code, true]))
}

/** Toggleable list of swing desk strategies (long-only). */
export default function SwingStrategyPanel({ strategies = [], compact = false }) {
  const [enabled, setEnabled] = useState(() => loadEnabled(strategies))

  useEffect(() => {
    setEnabled((prev) => {
      const next = { ...prev }
      for (const s of strategies) {
        if (next[s.code] === undefined) next[s.code] = true
      }
      return next
    })
  }, [strategies])

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(enabled))
  }, [enabled])

  if (!strategies.length) return null

  const list = (
    <div className="space-y-2">
      {strategies.map((s) => (
        <label
          key={s.code}
          className="flex items-start gap-3 rounded-lg border border-slate-800/80 bg-slate-950/40 p-3 cursor-pointer hover:border-violet-500/30"
        >
          <input
            type="checkbox"
            checked={enabled[s.code] !== false}
            onChange={(e) => setEnabled((prev) => ({ ...prev, [s.code]: e.target.checked }))}
            className="mt-1 accent-violet-500"
          />
          <span className="min-w-0">
            <span className="font-mono text-xs text-violet-300">{s.code}</span>
            <span className="block text-sm font-medium">{s.label}</span>
            {s.description && <span className="block text-xs text-slate-500 mt-0.5">{s.description}</span>}
          </span>
        </label>
      ))}
    </div>
  )

  if (compact) {
    return (
      <div className="mb-4 rounded-lg border border-violet-500/20 bg-violet-500/5 p-3">
        <p className="text-violet-400 text-xs uppercase tracking-widest mb-1">Strategy modules</p>
        <p className="text-xs text-slate-500 mb-2">Enable for AI scan · save settings to apply</p>
        {list}
      </div>
    )
  }

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <p className="text-violet-400 text-xs uppercase tracking-widest">Strategies</p>
      <h3 className="font-semibold mt-1">Swing Modules</h3>
      <p className="text-xs text-slate-500 mt-1 mb-3">Long-only · multi-day holds · delivery cost model</p>
      {list}
    </section>
  )
}

export function getEnabledSwingCodes() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const map = JSON.parse(raw)
    return Object.entries(map)
      .filter(([, on]) => on)
      .map(([code]) => code)
  } catch {
    return null
  }
}
