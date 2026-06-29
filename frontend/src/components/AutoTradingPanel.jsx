import { useEffect, useState } from 'react'
import { fetchAutoTrading, runAutoTradingNow, updateAutoTrading } from '../api'

const ENGINE_META = {
  scalping: {
    title: 'Scalping Bot',
    subtitle: 'NIFTY / BANKNIFTY options · 1m / 3m / 5m',
    accent: 'amber',
    productLabel: 'Intraday · Market',
  },
  intraday: {
    title: 'Intraday Bot',
    subtitle: 'Scanner hits + momentum confirmations · 15m',
    accent: 'cyan',
    productLabel: 'Intraday · Market',
  },
  swing: {
    title: 'Swing Bot',
    subtitle: 'Daily / weekly Nifty 50 setups',
    accent: 'violet',
    productLabel: 'Delivery · Market',
  },
}

function formatApiError(err, fallback) {
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join('; ')
  return err.message || fallback
}

function formatTime(value) {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleTimeString()
  } catch {
    return value
  }
}

function Stat({ label, value }) {
  return (
    <div className="rounded-lg bg-slate-950/50 border border-slate-800 px-3 py-2">
      <p className="text-slate-500">{label}</p>
      <p className="text-slate-200 font-medium mt-0.5">{value}</p>
    </div>
  )
}

function accentClasses(accent, enabled) {
  if (accent === 'amber') {
    return enabled
      ? 'border-amber-500/40 bg-amber-500/5'
      : 'border-slate-800'
  }
  if (accent === 'cyan') {
    return enabled ? 'border-cyan-500/40 bg-cyan-500/5' : 'border-slate-800'
  }
  return enabled ? 'border-violet-500/40 bg-violet-500/5' : 'border-slate-800'
}

function toggleButtonClasses(accent, enabled) {
  if (enabled) {
    return 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
  }
  if (accent === 'amber') return 'bg-amber-500 hover:bg-amber-400 text-slate-950'
  if (accent === 'cyan') return 'bg-cyan-500 hover:bg-cyan-400 text-slate-950'
  return 'bg-violet-500 hover:bg-violet-400 text-slate-950'
}

function EngineAutoTradingCard({ engine, meta, engineStatus, globalStatus, onRefresh }) {
  const [maxOrders, setMaxOrders] = useState(10)
  const [maxOrderAmount, setMaxOrderAmount] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [message, setMessage] = useState(null)

  const config = engineStatus?.config || {}
  const stats = engineStatus?.stats || {}
  const enabled = Boolean(config.enabled)

  useEffect(() => {
    setMaxOrders(config.max_orders_per_day ?? 10)
    setMaxOrderAmount(
      config.max_order_amount != null && config.max_order_amount > 0
        ? String(config.max_order_amount)
        : ''
    )
  }, [config.max_orders_per_day, config.max_order_amount])

  const save = async (nextEnabled = enabled) => {
    setLoading(true)
    setError(null)
    setMessage(null)
    const amount = maxOrderAmount === '' ? 0 : Number(maxOrderAmount)
    if (nextEnabled && (!Number.isFinite(amount) || amount <= 0)) {
      setError('Set max order amount (₹) before enabling this bot')
      setLoading(false)
      return
    }
    try {
      await updateAutoTrading({
        engine,
        enabled: nextEnabled,
        max_orders_per_day: Number(maxOrders),
        ...(Number.isFinite(amount) && amount > 0 ? { max_order_amount: amount } : {}),
      })
      setMessage(nextEnabled ? `${meta.title} enabled` : `${meta.title} disabled`)
      onRefresh?.()
    } catch (err) {
      setError(formatApiError(err, 'Unable to update auto trading settings'))
    } finally {
      setLoading(false)
    }
  }

  const runNow = async () => {
    setLoading(true)
    setError(null)
    setMessage(null)
    try {
      const result = await runAutoTradingNow(engine)
      const count = result.executed?.length || 0
      setMessage(
        count > 0
          ? `Executed ${count} order(s)`
          : 'No new orders — check AI approvals and engine limits'
      )
      onRefresh?.()
    } catch (err) {
      setError(formatApiError(err, 'Auto trading run failed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <article className={`rounded-xl border bg-slate-950/40 p-4 ${accentClasses(meta.accent, enabled)}`}>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
        <div>
          <p className="text-xs uppercase tracking-widest text-slate-500">{meta.productLabel}</p>
          <h4 className="font-semibold text-lg">{meta.title}</h4>
          <p className="text-sm text-slate-400 mt-1">{meta.subtitle}</p>
        </div>
        <button
          type="button"
          disabled={loading}
          onClick={() => save(!enabled)}
          className={`rounded-lg px-3 py-2 text-sm font-semibold disabled:opacity-50 ${toggleButtonClasses(meta.accent, enabled)}`}
        >
          {loading ? 'Saving…' : enabled ? 'Disable' : 'Enable'}
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 mb-3">
        <label className="block text-sm">
          <span className="text-slate-400">Max orders per day</span>
          <input
            type="number"
            min="1"
            max="500"
            value={maxOrders}
            onChange={(event) => setMaxOrders(event.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-400">Max amount per order (₹)</span>
          <input
            type="number"
            min="1"
            step="100"
            placeholder="e.g. 10000"
            value={maxOrderAmount}
            onChange={(event) => setMaxOrderAmount(event.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
          />
        </label>
      </div>
      <p className="text-[11px] text-slate-500 mb-3">
        Qty = max amount ÷ entry price, scaled by AI recommended size %. Capped by risk limits.
      </p>

      <div className="flex flex-wrap gap-2 mb-3">
        <button
          type="button"
          disabled={loading}
          onClick={() => save(enabled)}
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
        >
          Save Limits
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={runNow}
          className="rounded-lg border border-slate-600 px-3 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
        >
          Run Once
        </button>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 text-xs">
        <Stat label="Status" value={enabled ? 'ON' : 'OFF'} />
        <Stat label="Orders today" value={stats.orders_today ?? 0} />
        <Stat
          label="Max / order"
          value={config.max_order_amount > 0 ? `₹${Number(config.max_order_amount).toLocaleString('en-IN')}` : '—'}
        />
        <Stat label="AI approvals" value={engineStatus?.ai_approvals ?? 0} />
        <Stat label="Mode" value={globalStatus?.trading_mode || 'paper'} />
        <Stat label="Last run" value={formatTime(stats.last_run_at)} />
        <Stat label="Last order" value={formatTime(stats.last_order_at)} />
      </div>

      {stats.last_error && (
        <p className="mt-3 text-sm text-amber-400">Last issue: {stats.last_error}</p>
      )}
      {message && <p className="mt-3 text-sm text-emerald-400">{message}</p>}
      {error && <p className="mt-3 text-sm text-rose-400">{error}</p>}
    </article>
  )
}

export default function AutoTradingPanel() {
  const [status, setStatus] = useState(null)
  const [globalLossPct, setGlobalLossPct] = useState(5)
  const [loadingGlobal, setLoadingGlobal] = useState(false)
  const [globalError, setGlobalError] = useState(null)
  const [globalMessage, setGlobalMessage] = useState(null)

  const refresh = () => {
    fetchAutoTrading()
      .then((data) => {
        setStatus(data)
        setGlobalLossPct(data.config?.max_daily_loss_pct ?? 5)
      })
      .catch(() => setStatus(null))
  }

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 15000)
    return () => clearInterval(interval)
  }, [])

  const saveGlobalRisk = async () => {
    setLoadingGlobal(true)
    setGlobalError(null)
    setGlobalMessage(null)
    try {
      await updateAutoTrading({ max_daily_loss_pct: Number(globalLossPct) })
      setGlobalMessage('Global risk limit saved')
      refresh()
    } catch (err) {
      setGlobalError(formatApiError(err, 'Unable to save risk limit'))
    } finally {
      setLoadingGlobal(false)
    }
  }

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-4">
        <p className="text-violet-400 text-xs uppercase tracking-widest">AI Auto Trading</p>
        <h3 className="font-semibold text-lg">Strategy Execution Bots</h3>
        <p className="text-sm text-slate-400 mt-1">
          Enable scalping, intraday, or swing independently. Approved AI signals are placed every minute
          in paper or live mode.
        </p>
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3 mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="block text-sm flex-1 min-w-[180px]">
            <span className="text-slate-400">Global max daily loss (% of equity)</span>
            <input
              type="number"
              min="0.1"
              max="100"
              step="0.1"
              value={globalLossPct}
              onChange={(event) => setGlobalLossPct(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
            />
          </label>
          <button
            type="button"
            disabled={loadingGlobal}
            onClick={saveGlobalRisk}
            className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
          >
            {loadingGlobal ? 'Saving…' : 'Save Global Risk'}
          </button>
        </div>
        {status?.risk && (
          <div className="grid gap-2 sm:grid-cols-3 mt-3 text-xs">
            <Stat label="Risk status" value={status.risk.can_trade ? 'OK' : 'Blocked'} />
            <Stat label="Daily loss used" value={`${status.risk.daily_loss_used_pct ?? 0}%`} />
            <Stat label="Total orders today" value={status.stats?.orders_today ?? 0} />
          </div>
        )}
        {globalMessage && <p className="mt-3 text-sm text-emerald-400">{globalMessage}</p>}
        {globalError && <p className="mt-3 text-sm text-rose-400">{globalError}</p>}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {Object.entries(ENGINE_META).map(([engine, meta]) => (
          <EngineAutoTradingCard
            key={engine}
            engine={engine}
            meta={meta}
            engineStatus={status?.engines?.[engine]}
            globalStatus={status}
            onRefresh={refresh}
          />
        ))}
      </div>
    </section>
  )
}
