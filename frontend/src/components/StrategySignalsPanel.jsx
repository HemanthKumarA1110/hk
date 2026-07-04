import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchIntradayStrategies, fetchStrategyStatus, fetchSwingStrategies, runStrategies } from '../api'
import { filterStrategiesForDesk } from '../utils/strategyFilters'

function formatWhen(value) {
  if (!value) return null
  return new Date(value).toLocaleString('en-IN')
}

function formatApiError(err) {
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join('; ')
  return err.message || 'Request failed'
}

function EngineCard({ config, payload, strategies = [] }) {
  const signals = payload?.signals || []
  const minScore = config?.min_score ?? 0
  const codes = config?.catalog_codes || strategies.map((s) => s.code).filter(Boolean)

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 flex flex-col">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <h3 className="font-semibold">{config?.title || config?.engine}</h3>
          <p className="text-xs text-cyan-400/90 mt-0.5 font-mono">{config?.strategy_name}</p>
          {config?.strategy_version != null && (
            <p className="text-[10px] text-amber-400/80 mt-0.5">Desk v{config.strategy_version}</p>
          )}
        </div>
        {config?.desk_path && (
          <Link
            to={config.desk_path}
            className="text-[10px] border border-slate-700 rounded px-2 py-1 hover:bg-slate-800 shrink-0"
          >
            Desk →
          </Link>
        )}
      </div>

      {config?.summary && <p className="text-xs text-slate-400 mb-3">{config.summary}</p>}

      <dl className="text-xs text-slate-500 space-y-1 mb-3 border-b border-slate-800 pb-3">
        <div className="flex gap-2">
          <dt className="text-slate-600 shrink-0">Universe</dt>
          <dd>{config?.universe}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-slate-600 shrink-0">Timeframes</dt>
          <dd>{(config?.timeframes || []).join(', ')}</dd>
        </div>
        {config?.session && (
          <div className="flex gap-2">
            <dt className="text-slate-600 shrink-0">Session</dt>
            <dd>{config.session}</dd>
          </div>
        )}
        <div className="flex gap-2">
          <dt className="text-slate-600 shrink-0">Target</dt>
          <dd>{config?.target_logic}</dd>
        </div>
        {config?.ai_mode && (
          <div className="flex gap-2">
            <dt className="text-slate-600 shrink-0">AI / Manual</dt>
            <dd>{config.ai_mode}</dd>
          </div>
        )}
      </dl>

      {(codes.length > 0 || strategies.length > 0) && (
        <div className="mb-3">
          <p className="text-[10px] uppercase tracking-wider text-slate-600 mb-1.5">
            Catalog ({config?.strategy_count ?? codes.length})
          </p>
          <div className="flex flex-wrap gap-1 max-h-20 overflow-auto">
            {(strategies.length ? strategies : codes.map((c) => ({ code: c }))).map((s) => (
              <span
                key={s.code}
                className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-400"
                title={s.label}
              >
                {s.code}
              </span>
            ))}
          </div>
        </div>
      )}

      {config?.confirmations?.length > 0 && (
        <div className="mb-3">
          <p className="text-[10px] uppercase tracking-wider text-slate-600 mb-1.5">AI & filters</p>
          <ul className="space-y-1 max-h-24 overflow-auto text-xs">
            {config.confirmations.map((item) => (
              <li key={item.name} className="text-slate-400 leading-snug">
                {item.label}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-auto pt-2 border-t border-slate-800">
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs text-slate-500">
            {signals.length} signal{signals.length === 1 ? '' : 's'}
            {payload?.generated_at ? ` · ${formatWhen(payload.generated_at)}` : ''}
          </p>
          <span className="text-[10px] text-slate-600">Min score {minScore}</span>
        </div>
        <div className="space-y-2 max-h-48 overflow-auto">
          {signals.length === 0 && (
            <p className="text-sm text-slate-500">
              No qualified signals. Run engines during market hours, or use desk scan on Intraday/Swing pages.
            </p>
          )}
          {signals.map((signal) => (
            <div
              key={`${signal.symbol}-${signal.side}-${signal.timeframe}`}
              className="border border-slate-800 rounded-lg p-2 text-sm"
            >
              <div className="flex justify-between">
                <span className="font-medium">{signal.symbol}</span>
                <span className={signal.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}>
                  {signal.side}
                </span>
              </div>
              <div className="flex justify-between text-slate-400 mt-1 text-xs">
                <span>
                  Score {Number(signal.score || 0).toFixed(0)} · {signal.timeframe}
                </span>
                <span>{((signal.confidence || 0) * 100).toFixed(0)}% conf</span>
              </div>
              <div className="grid grid-cols-3 gap-2 mt-2 text-xs font-mono">
                <span>Entry {signal.entry}</span>
                <span>SL {signal.stoploss}</span>
                <span>T {signal.targets?.[0] ?? '—'}</span>
              </div>
              {signal.confirmations?.length > 0 && (
                <p className="text-xs text-slate-500 mt-1">
                  Confirmations: {signal.confirmations.filter((c) => c.passed).length}/
                  {signal.confirmations.length}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default function StrategySignalsPanel({ refreshToken = 0 }) {
  const [status, setStatus] = useState(null)
  const [intradayStrategies, setIntradayStrategies] = useState([])
  const [swingStrategies, setSwingStrategies] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(() => {
    fetchStrategyStatus()
      .then((data) => {
        setStatus(data)
        setError('')
      })
      .catch((err) => {
        setError(formatApiError(err))
      })
    fetchIntradayStrategies()
      .then((d) => setIntradayStrategies(filterStrategiesForDesk('intraday', d?.strategies || [])))
      .catch(() => null)
    fetchSwingStrategies()
      .then((d) => setSwingStrategies(filterStrategiesForDesk('swing', d?.strategies || [])))
      .catch(() => null)
  }, [])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 30000)
    return () => clearInterval(timer)
  }, [refresh, refreshToken])

  const handleRun = async () => {
    setBusy(true)
    setError('')
    try {
      await runStrategies()
      refresh()
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setBusy(false)
    }
  }

  const configs = status?.engine_configs || []
  const payloadByEngine = {
    scalping: status?.scalping,
    intraday: status?.intraday,
    swing: status?.swing,
  }

  const strategiesByEngine = {
    scalping: [],
    intraday: intradayStrategies,
    swing: swingStrategies,
  }

  const cards =
    configs.length > 0
      ? configs
      : [
          { engine: 'scalping', title: 'Scalping Desk', min_score: 80 },
          { engine: 'intraday', title: 'Intraday Desk', min_score: 65 },
          { engine: 'swing', title: 'Swing Desk', min_score: 60 },
        ]

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <p className="text-cyan-400 text-xs uppercase tracking-widest">Orchestrator</p>
          <h2 className="text-xl font-semibold">Live engine signals</h2>
          <p className="text-xs text-slate-500 mt-1">
            Cached picks from strategy orchestrator · refreshes every 30s
          </p>
        </div>
        <button
          type="button"
          onClick={handleRun}
          disabled={busy}
          className="rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 px-4 py-2 text-sm font-semibold disabled:opacity-50"
        >
          {busy ? 'Running…' : 'Run now'}
        </button>
      </div>

      {error && <p className="text-rose-400 text-sm mb-4">{error}</p>}

      <div className="grid gap-4 lg:grid-cols-3">
        {cards.map((config) => (
          <EngineCard
            key={config.engine}
            config={config}
            payload={payloadByEngine[config.engine]}
            strategies={strategiesByEngine[config.engine]}
          />
        ))}
      </div>
    </section>
  )
}
