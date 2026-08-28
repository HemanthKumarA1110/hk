import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  fetchIntradayStrategies,
  fetchScalpingStrategies,
  fetchSwingStrategies,
} from '../api'
import { filterStrategiesForDesk } from '../utils/strategyFilters'

const DESK_META = {
  scalping: {
    label: 'Scalping',
    accent: 'amber',
    paths: [
      { to: '/scalping/nifty50', label: 'Nifty desk' },
      { to: '/scalping/banknifty', label: 'Bank Nifty desk' },
    ],
  },
  intraday: {
    label: 'Intraday',
    accent: 'cyan',
    paths: [{ to: '/intraday', label: 'Intraday desk' }],
  },
  swing: {
    label: 'Swing',
    accent: 'violet',
    paths: [{ to: '/swing', label: 'Swing desk' }],
  },
}

const FAMILY_STYLE = {
  battle: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  adaptive: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
  smc: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30',
  intraday: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30',
  swing: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
}

function StrategyRow({ strategy, showInstruments = false }) {
  const family = strategy.family || 'adaptive'
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-emerald-400">{strategy.code}</span>
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded border ${
                FAMILY_STYLE[family] || 'border-slate-700 text-slate-400'
              }`}
            >
              {family}
            </span>
            {strategy.enabled != null && (
              <span
                className={`text-[10px] px-1.5 py-0.5 rounded ${
                  strategy.enabled ? 'bg-emerald-500/15 text-emerald-400' : 'bg-slate-800 text-slate-500'
                }`}
              >
                {strategy.enabled ? 'enabled' : 'off'}
              </span>
            )}
          </div>
          <p className="font-medium text-sm mt-1">{strategy.label}</p>
          {strategy.description && (
            <p className="text-xs text-slate-500 mt-1 leading-relaxed">{strategy.description}</p>
          )}
        </div>
      </div>
      {showInstruments && strategy.instruments?.length > 0 && (
        <p className="text-[10px] text-slate-600 mt-2">
          Instruments: {strategy.instruments.join(', ')}
        </p>
      )}
      {strategy.best_regimes?.length > 0 && (
        <p className="text-[10px] text-slate-600 mt-1">
          Best regimes: {strategy.best_regimes.join(' · ')}
        </p>
      )}
    </div>
  )
}

function DeskCatalogSection({ desk, strategies, meta, loading }) {
  const accentBorder =
    meta.accent === 'amber'
      ? 'border-amber-500/30'
      : meta.accent === 'cyan'
        ? 'border-cyan-500/30'
        : 'border-violet-500/30'

  return (
    <section className={`rounded-xl border ${accentBorder} bg-slate-900/60 p-4`}>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <p
            className={`text-xs uppercase tracking-widest ${
              meta.accent === 'amber'
                ? 'text-amber-400'
                : meta.accent === 'cyan'
                  ? 'text-cyan-400'
                  : 'text-violet-400'
            }`}
          >
            {meta.label} · {strategies.length} strategies
          </p>
          <h3 className="font-semibold text-lg mt-1">{meta.label} catalog</h3>
        </div>
        <div className="flex flex-wrap gap-2">
          {meta.paths.map((p) => (
            <Link
              key={p.to}
              to={p.to}
              className="text-xs border border-slate-700 rounded-lg px-3 py-1.5 hover:bg-slate-800"
            >
              {p.label} →
            </Link>
          ))}
          <Link to="/live" className="text-xs border border-emerald-500/30 text-emerald-400 rounded-lg px-3 py-1.5 hover:bg-emerald-500/10">
            Auto trade →
          </Link>
        </div>
      </div>

      {loading && <p className="text-sm text-slate-500">Loading catalog…</p>}
      {!loading && strategies.length === 0 && (
        <p className="text-sm text-slate-500">No strategies loaded.</p>
      )}
      <div className="space-y-2">
        {strategies.map((s) => (
          <StrategyRow key={s.code} strategy={s} showInstruments={desk === 'scalping'} />
        ))}
      </div>
    </section>
  )
}

/** Full strategy catalog across scalping, intraday, and swing desks. */
export default function StrategyCatalogPanel() {
  const [scalpNifty, setScalpNifty] = useState([])
  const [scalpBank, setScalpBank] = useState([])
  const [intraday, setIntraday] = useState([])
  const [swing, setSwing] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const [nifty, bank, intra, sw] = await Promise.all([
          fetchScalpingStrategies('nifty50').catch(() => ({ strategies: [] })),
          fetchScalpingStrategies('banknifty').catch(() => ({ strategies: [] })),
          fetchIntradayStrategies().catch(() => ({ strategies: [] })),
          fetchSwingStrategies().catch(() => ({ strategies: [] })),
        ])
        if (cancelled) return
        setScalpNifty(filterStrategiesForDesk('scalping', nifty?.strategies || []))
        setScalpBank(filterStrategiesForDesk('scalping', bank?.strategies || []))
        setIntraday(filterStrategiesForDesk('intraday', intra?.strategies || []))
        setSwing(filterStrategiesForDesk('swing', sw?.strategies || []))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const scalpMerged = [...scalpNifty]
  for (const s of scalpBank) {
    if (!scalpMerged.find((x) => x.code === s.code)) scalpMerged.push(s)
  }
  scalpMerged.sort((a, b) => String(a.code).localeCompare(String(b.code)))

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 text-sm text-slate-400">
        <p className="text-emerald-400 text-xs uppercase tracking-widest mb-2">Reference codes</p>
        <p>
          Each strategy has a stable code (<span className="font-mono text-slate-300">SCALP-BT-003</span>,{' '}
          <span className="font-mono text-slate-300">INTRA-ORB</span>,{' '}
          <span className="font-mono text-slate-300">INTRA-VWAP-ORB</span>,{' '}
          <span className="font-mono text-slate-300">SWING-EMA</span>). Use these when requesting changes,
          running backtests, or enabling modules on the Live Trading page.
        </p>
        <p className="mt-2">
          <span className="text-slate-300">AI layer (v8):</span> entry confirmation vetoes weak signals;
          dynamic exit cuts losses without exiting winners early; battle-tested scalps skip redundant AI entry filters.
        </p>
      </div>

      <DeskCatalogSection
        desk="scalping"
        strategies={scalpMerged}
        meta={DESK_META.scalping}
        loading={loading}
      />
      <DeskCatalogSection
        desk="intraday"
        strategies={intraday}
        meta={DESK_META.intraday}
        loading={loading}
      />
      <DeskCatalogSection
        desk="swing"
        strategies={swing}
        meta={DESK_META.swing}
        loading={loading}
      />
    </div>
  )
}
