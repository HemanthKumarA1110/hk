import { useCallback, useEffect, useState } from 'react'
import {
  evaluateScalpingDesk,
  fetchScalpingDesk,
  saveScalpingDeskConfig,
  startMarketStream,
  toggleScalpingAutoTrading,
} from '../api'
import { INSTRUMENT_META } from '../types/scalping.types'
import ScalpingStrategySelector from './ScalpingStrategySelector'
import StreamStatusPanel from './scalping/StreamStatusPanel'

function formatApiError(err, fallback) {
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join('; ')
  return err.message || fallback
}

/** Compact scalping auto-trading card for the Live Trading hub. */
export default function ScalpingAutoTradingPanel({ instrument = 'nifty50' }) {
  const meta = INSTRUMENT_META[instrument] || { label: instrument, underlying: instrument }
  const [desk, setDesk] = useState(null)
  const [draft, setDraft] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [showModal, setShowModal] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await fetchScalpingDesk(instrument)
      setDesk(data)
      setDraft(data?.config || null)
    } catch {
      /* poll */
    }
  }, [instrument])

  useEffect(() => {
    load()
    const timer = setInterval(load, 30_000)
    return () => clearInterval(timer)
  }, [load])

  const cfg = draft || desk?.config || {}
  const state = desk?.state || {}
  const autoOn = Boolean(cfg.auto_trading_enabled)
  const mode = cfg.strategy_mode || 'auto'

  const updateDraft = (key, value) => {
    if (typeof key === 'object' && key !== null) {
      setDraft((prev) => ({ ...(prev || cfg), ...key }))
      return
    }
    setDraft((prev) => ({ ...(prev || cfg), [key]: value }))
  }

  const persistConfig = async (nextCfg) => {
    setLoading(true)
    setError('')
    setMessage('')
    try {
      const saved = await saveScalpingDeskConfig(instrument, nextCfg)
      setDraft(saved)
      setMessage('Settings saved')
      await load()
    } catch (err) {
      setError(formatApiError(err, 'Failed to save settings'))
    } finally {
      setLoading(false)
    }
  }

  const handleSave = () => persistConfig(draft || cfg)

  const handleToggle = async (enabled) => {
    setShowModal(false)
    setLoading(true)
    setError('')
    setMessage('')
    try {
      if (enabled) {
        await startMarketStream().catch(() => null)
        await saveScalpingDeskConfig(instrument, { ...(draft || cfg), auto_trading_enabled: true })
      }
      await toggleScalpingAutoTrading(instrument, enabled)
      setMessage(
        enabled
          ? 'Auto trading enabled — Live Market Engine ON for ticks'
          : 'Auto trading disabled'
      )
      await load()
    } catch (err) {
      setError(formatApiError(err, 'Failed to toggle auto trading'))
    } finally {
      setLoading(false)
    }
  }

  const handleRunNow = async () => {
    setLoading(true)
    setError('')
    setMessage('')
    try {
      await evaluateScalpingDesk(instrument)
      setMessage('Evaluation cycle complete')
      await load()
    } catch (err) {
      setError(formatApiError(err, 'Evaluate failed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <section
        className={`rounded-xl border p-4 ${
          autoOn ? 'border-amber-500/40 bg-amber-500/5' : 'border-slate-800 bg-slate-900/60'
        }`}
      >
        <div className="flex flex-wrap items-start justify-between gap-4 mb-4">
          <div>
            <p className="text-amber-400 text-xs uppercase tracking-widest">Scalping · {meta.underlying}</p>
            <h3 className="font-semibold text-lg mt-1">{meta.label}</h3>
            <p className="text-xs text-slate-500 mt-1">
              Index options · AI adaptive entries · live Angel One · live stream ~1s
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={handleSave}
              disabled={loading}
              className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
            >
              Save
            </button>
            <button
              type="button"
              onClick={handleRunNow}
              disabled={loading}
              className="rounded-lg border border-amber-500/40 text-amber-300 px-3 py-2 text-sm hover:bg-amber-500/10 disabled:opacity-50"
            >
              Run now
            </button>
            <button
              type="button"
              onClick={() => (autoOn ? handleToggle(false) : setShowModal(true))}
              disabled={loading}
              className={`rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50 ${
                autoOn
                  ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                  : 'bg-amber-500 text-slate-950'
              }`}
            >
              {autoOn ? 'Turn OFF' : 'Turn ON'}
            </button>
          </div>
        </div>

        {error && <p className="text-rose-400 text-sm mb-3">{error}</p>}
        {message && <p className="text-emerald-400 text-sm mb-3">{message}</p>}

        <StreamStatusPanel deskStatus={desk?.stream_status} compact onStreamStarted={load} />

        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4 mb-4">
          <label className="block text-sm">
            <span className="text-slate-400">Capital (₹)</span>
            <input
              type="number"
              value={cfg.capital ?? 100000}
              onChange={(e) => updateDraft('capital', Number(e.target.value))}
              className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-400">Max trades / day</span>
            <input
              type="number"
              min={1}
              value={cfg.max_trades_per_day ?? 3}
              onChange={(e) => updateDraft('max_trades_per_day', Number(e.target.value))}
              className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-400">Max loss / day (₹)</span>
            <input
              type="number"
              min={1}
              value={cfg.max_loss_per_day ?? 5000}
              onChange={(e) => updateDraft('max_loss_per_day', Number(e.target.value))}
              className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2"
            />
          </label>
          <div className="block text-sm">
            <span className="text-slate-400">Strategy mode</span>
            <div className="flex gap-2 mt-1">
              {[
                ['auto', 'All strategies'],
                ['manual', 'Selected only'],
              ].map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => updateDraft('strategy_mode', value)}
                  className={`flex-1 rounded-lg py-2 text-xs font-medium ${
                    mode === value
                      ? 'bg-amber-500 text-slate-950'
                      : 'border border-slate-700 text-slate-400'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <ScalpingStrategySelector
          instrument={instrument}
          strategies={desk?.available_strategies || []}
          settings={cfg.strategy_settings || {}}
          mode={mode}
          fixedCode={cfg.fixed_strategy_code}
          onSettingsChange={(next) => updateDraft('strategy_settings', next)}
          onFixedChange={(code, picked) =>
            updateDraft({
              fixed_strategy_code: code,
              fixed_strategy_id: picked?.id,
              strategy_family: picked?.family,
            })
          }
          compact
        />

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-sm">
          <Stat label="Status" value={autoOn ? 'Running' : 'Off'} highlight={autoOn} />
          <Stat label="Trades today" value={state.trades_today ?? 0} />
          <Stat
            label="Daily P&L"
            value={`₹${Number(state.daily_pnl ?? 0).toLocaleString('en-IN')}`}
            negative={Number(state.daily_pnl ?? 0) < 0}
          />
          <Stat
            label="Active trade"
            value={state.active_trade ? 'Yes' : 'None'}
            highlight={Boolean(state.active_trade)}
          />
        </div>

        {desk?.signal?.signal_type && (
          <p className="mt-3 text-xs text-amber-200/80 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
            Latest signal: {desk.signal.signal_type} · {desk.signal.status}
            {desk.signal.ai?.confidence != null ? ` · AI ${desk.signal.ai.confidence}%` : ''}
          </p>
        )}
      </section>

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="max-w-md rounded-xl border border-slate-700 bg-slate-900 p-6">
            <h3 className="text-lg font-semibold text-amber-300">Enable {meta.underlying} scalping?</h3>
            <p className="text-sm text-slate-400 mt-3">
              Places live Angel One orders when AI confidence passes filters.
              Review capital and max loss before enabling.
            </p>
            <div className="flex gap-3 mt-6">
              <button
                type="button"
                onClick={() => setShowModal(false)}
                className="flex-1 rounded-lg border border-slate-700 py-2"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => handleToggle(true)}
                className="flex-1 rounded-lg bg-amber-500 text-slate-950 py-2 font-semibold"
              >
                Enable
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function Stat({ label, value, highlight, negative }) {
  return (
    <div className="rounded-lg bg-slate-950/50 border border-slate-800 px-3 py-2">
      <p className="text-slate-500 text-xs">{label}</p>
      <p
        className={`font-medium mt-0.5 ${
          negative ? 'text-rose-400' : highlight ? 'text-emerald-400' : 'text-slate-200'
        }`}
      >
        {value}
      </p>
    </div>
  )
}
