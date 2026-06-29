import { useCallback, useEffect, useState } from 'react'
import { fetchStrategyStatus, runStrategies } from '../api'

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

function EngineCard({ config, payload }) {
  const signals = payload?.signals || []
  const minScore = config?.min_score ?? 0

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 flex flex-col">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <h3 className="font-semibold">{config?.title || config?.engine}</h3>
          <p className="text-xs text-cyan-400/90 mt-0.5 font-mono">{config?.strategy_name}</p>
        </div>
        <span className="text-xs text-slate-500 shrink-0">Min score {minScore}</span>
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
        <div className="flex gap-2">
          <dt className="text-slate-600 shrink-0">Target</dt>
          <dd>{config?.target_logic}</dd>
        </div>
      </dl>

      {config?.confirmations?.length > 0 && (
        <div className="mb-3">
          <p className="text-[10px] uppercase tracking-wider text-slate-600 mb-1.5">Confirmations</p>
          <ul className="space-y-1 max-h-28 overflow-auto text-xs">
            {config.confirmations.map((item) => (
              <li key={item.name} className="flex justify-between gap-2 text-slate-400">
                <span>{item.label}</span>
                <span className="text-slate-600 shrink-0">w{item.weight}</span>
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
        </div>
        <div className="space-y-2 max-h-48 overflow-auto">
          {signals.length === 0 && (
            <p className="text-sm text-slate-500">
              No qualified signals yet. Run strategies during market hours with live ticks, or use the
              Intraday / Swing desk scan buttons.
            </p>
          )}
          {signals.map((signal) => (
            <div
              key={`${signal.symbol}-${signal.side}-${signal.timeframe}`}
              className="border border-slate-800 rounded-lg p-2 text-sm"
            >
              <div className="flex justify-between">
                <span className="font-medium">{signal.symbol}</span>
                <span className={signal.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}>{signal.side}</span>
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
              <p className="text-xs text-slate-500 mt-1">
                Confirmations: {signal.confirmations?.filter((c) => c.passed).length ?? 0}/
                {signal.confirmations?.length ?? 0}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default function StrategySignalsPanel({ refreshToken = 0 }) {
  const [status, setStatus] = useState(null)
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

  const cards =
    configs.length > 0
      ? configs
      : [
          { engine: 'scalping', title: 'Scalping (NIFTY/BANKNIFTY)', min_score: 80 },
          { engine: 'intraday', title: 'Intraday Top Picks', min_score: 65 },
          { engine: 'swing', title: 'Swing Setups', min_score: 60 },
        ]

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <p className="text-cyan-400 text-xs uppercase tracking-widest">Phase 3</p>
          <h2 className="text-xl font-semibold">Strategy Engines</h2>
          <p className="text-xs text-slate-500 mt-1">Weighted confirmation scoring · auto-refresh every 30s</p>
        </div>
        <button
          type="button"
          onClick={handleRun}
          disabled={busy}
          className="rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 px-4 py-2 text-sm font-semibold disabled:opacity-50"
        >
          {busy ? 'Running…' : 'Run Now'}
        </button>
      </div>

      {error && <p className="text-rose-400 text-sm mb-4">{error}</p>}

      <div className="grid gap-4 lg:grid-cols-3">
        {cards.map((config) => (
          <EngineCard key={config.engine} config={config} payload={payloadByEngine[config.engine]} />
        ))}
      </div>
    </section>
  )
}
