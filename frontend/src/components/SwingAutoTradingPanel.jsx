import { useCallback, useEffect, useState } from 'react'
import {
  evaluateSwingDesk,
  fetchSwingDesk,
  saveSwingDeskConfig,
  toggleSwingAutoTrading,
} from '../api'
import { getEnabledSwingCodes } from './SwingStrategyPanel'
import SwingStrategyPanel from './SwingStrategyPanel'

function formatApiError(err, fallback) {
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join('; ')
  return err.message || fallback
}

function buildStrategySettings(strategies) {
  const enabledCodes = getEnabledSwingCodes()
  const settings = {}
  for (const s of strategies) {
    settings[s.code] = {
      enabled: enabledCodes ? enabledCodes.includes(s.code) : true,
    }
  }
  return settings
}

/** Swing desk auto-trading — AI or manual strategy, capital & daily limits. */
export default function SwingAutoTradingPanel({ strategies = [], isPaper = true, embedded = false }) {
  const [desk, setDesk] = useState(null)
  const [draft, setDraft] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [showModal, setShowModal] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await fetchSwingDesk()
      setDesk(data)
      setDraft(data?.config || null)
    } catch {
      /* ignore on poll */
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, 30_000)
    return () => clearInterval(timer)
  }, [load])

  const cfg = draft || desk?.config || {}
  const state = desk?.state || {}
  const guards = desk?.guards || {}
  const autoOn = Boolean(cfg.auto_trading_enabled)
  const mode = cfg.strategy_mode || 'ai'

  const updateDraft = (key, value) => {
    setDraft((prev) => ({ ...(prev || cfg), [key]: value }))
  }

  const persistConfig = async (nextCfg) => {
    setLoading(true)
    setError('')
    setMessage('')
    try {
      const payload = {
        ...nextCfg,
        swing_strategy_settings: buildStrategySettings(strategies),
      }
      const saved = await saveSwingDeskConfig(payload)
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
        await saveSwingDeskConfig({
          ...(draft || cfg),
          auto_trading_enabled: true,
          swing_strategy_settings: buildStrategySettings(strategies),
        })
      }
      await toggleSwingAutoTrading(enabled)
      setMessage(enabled ? 'Auto trading enabled' : 'Auto trading disabled')
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
      const result = await evaluateSwingDesk()
      const entries = result?.executed_entries?.length || 0
      const exits = result?.executed_exits?.length || 0
      setMessage(`Cycle complete · ${entries} entries · ${exits} exits`)
      await load()
    } catch (err) {
      setError(formatApiError(err, 'Auto cycle failed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <section
        className={`rounded-xl border p-4 ${embedded ? '' : 'mb-6'} ${
          autoOn ? 'border-violet-500/40 bg-violet-500/5' : 'border-slate-800 bg-slate-900/60'
        }`}
      >
        <div className="flex flex-wrap items-start justify-between gap-4 mb-4">
          <div>
            <p className="text-violet-400 text-xs uppercase tracking-widest">Auto Trading</p>
            <h3 className="font-semibold text-lg mt-1">Swing Bot</h3>
            <p className="text-xs text-slate-500 mt-1">
              AI picks top Nifty 50 stocks · multi-day delivery holds · strategy/AI exits ·{' '}
              {isPaper ? 'paper' : 'live'} orders
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={handleSave}
              disabled={loading}
              className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
            >
              Save settings
            </button>
            <button
              type="button"
              onClick={handleRunNow}
              disabled={loading || !autoOn}
              className="rounded-lg border border-violet-500/40 text-violet-300 px-4 py-2 text-sm hover:bg-violet-500/10 disabled:opacity-50"
            >
              Run now
            </button>
            <button
              type="button"
              onClick={() => (autoOn ? handleToggle(false) : setShowModal(true))}
              disabled={loading}
              className={`rounded-lg px-5 py-2 text-sm font-semibold disabled:opacity-50 ${
                autoOn
                  ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                  : 'bg-violet-500 text-slate-950'
              }`}
            >
              {autoOn ? 'Turn OFF' : 'Turn ON'}
            </button>
          </div>
        </div>

        {error && <p className="text-rose-400 text-sm mb-3">{error}</p>}
        {message && <p className="text-emerald-400 text-sm mb-3">{message}</p>}

        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5 mb-4">
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
              value={cfg.max_trades_per_day ?? 5}
              onChange={(e) => updateDraft('max_trades_per_day', Number(e.target.value))}
              className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-400">Max loss / day (₹)</span>
            <input
              type="number"
              min={1}
              value={cfg.max_daily_loss_inr ?? 5000}
              onChange={(e) => updateDraft('max_daily_loss_inr', Number(e.target.value))}
              className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-400">Max open positions</span>
            <input
              type="number"
              min={1}
              value={cfg.max_open_positions ?? 5}
              onChange={(e) => updateDraft('max_open_positions', Number(e.target.value))}
              className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2"
            />
          </label>
          <div className="block text-sm">
            <span className="text-slate-400">Strategy mode</span>
            <div className="flex gap-2 mt-1">
              {[
                ['ai', 'AI'],
                ['manual', 'Manual'],
              ].map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => updateDraft('strategy_mode', value)}
                  className={`flex-1 rounded-lg py-2 text-sm font-medium ${
                    mode === value
                      ? 'bg-violet-500 text-slate-950'
                      : 'border border-slate-700 text-slate-400'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {mode === 'manual' && (
          <label className="block text-sm mb-4 max-w-md">
            <span className="text-slate-400">Manual strategy</span>
            <select
              value={cfg.manual_strategy_code || 'SWING-EMA'}
              onChange={(e) => updateDraft('manual_strategy_code', e.target.value)}
              className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2"
            >
              {(getEnabledSwingCodes()?.length
                ? strategies.filter((s) => getEnabledSwingCodes().includes(s.code))
                : strategies
              ).map((s) => (
                <option key={s.code} value={s.code}>
                  {s.code} — {s.label}
                </option>
              ))}
            </select>
            <span className="text-xs text-slate-500 mt-1 block">
              Uses only the selected enabled strategy · top ranked picks from daily scan
            </span>
          </label>
        )}

        {mode === 'ai' && !embedded && (
          <p className="text-xs text-violet-300/80 bg-violet-500/5 border border-violet-500/20 rounded-lg px-3 py-2 mb-4">
            AI mode screens Nifty 50 on daily bars, ranks top stocks, and approves entries/exits via
            the decision engine. Enable strategies in the panel below — AI evaluates all enabled modules.
          </p>
        )}

        {embedded && strategies.length > 0 && (
          <SwingStrategyPanel strategies={strategies} compact />
        )}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5 text-sm">
          <Stat label="Status" value={autoOn ? 'Running' : 'Off'} highlight={autoOn} />
          <Stat label="Trades today" value={guards.trades_today ?? state.trades_today ?? 0} />
          <Stat
            label="Daily P&L"
            value={`₹${Number(guards.daily_pnl ?? state.daily_pnl ?? 0).toLocaleString('en-IN')}`}
            negative={Number(guards.daily_pnl ?? state.daily_pnl ?? 0) < 0}
          />
          <Stat
            label="Open positions"
            value={`${guards.open_positions ?? (state.active_positions || []).length}/${guards.max_open_positions ?? cfg.max_open_positions ?? 5}`}
          />
          <Stat
            label="Last run"
            value={
              state.last_run_at
                ? new Date(state.last_run_at).toLocaleTimeString('en-IN')
                : '—'
            }
          />
        </div>

        {(guards.alerts || []).length > 0 && (
          <ul className="mt-3 text-xs text-amber-300/90 space-y-1">
            {guards.alerts.map((a) => (
              <li key={a}>• {a}</li>
            ))}
          </ul>
        )}

        {(state.active_positions || []).length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <p className="text-xs text-slate-500 uppercase mb-2">Active positions</p>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-800">
                  <th className="py-1 text-left pr-3">Symbol</th>
                  <th className="py-1 text-left pr-3">Strategy</th>
                  <th className="py-1 text-left pr-3">Qty</th>
                  <th className="py-1 text-left">Entry</th>
                </tr>
              </thead>
              <tbody>
                {state.active_positions.map((p) => (
                  <tr key={p.symbol} className="border-b border-slate-800/60">
                    <td className="py-1.5 pr-3 font-medium">{p.symbol?.replace('-EQ', '')}</td>
                    <td className="py-1.5 pr-3 font-mono text-violet-300">{p.strategy_code}</td>
                    <td className="py-1.5 pr-3">{p.qty}</td>
                    <td className="py-1.5">₹{Number(p.entry).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="max-w-md rounded-xl border border-slate-700 bg-slate-900 p-6">
            <h3 className="text-lg font-semibold text-violet-300">Enable swing auto trading?</h3>
            <p className="text-sm text-slate-400 mt-3">
              The bot will scan Nifty 50 on daily data, pick top stocks, and place{' '}
              {isPaper ? 'paper' : 'live'} delivery orders. Positions may be held for several days.
              AI mode uses the decision engine for entry/exit — review capital and max loss settings first.
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
                className="flex-1 rounded-lg bg-violet-500 text-slate-950 py-2 font-semibold"
              >
                Enable auto trading
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
