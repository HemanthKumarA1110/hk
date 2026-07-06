import { useEffect, useState } from 'react'
import { fetchOrderStatus, setTradingMode } from '../api'

export default function TradingModeToggle({ onChange }) {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const refresh = () => {
    fetchOrderStatus()
      .then((data) => {
        setStatus(data)
        onChange?.(data)
      })
      .catch(() => setStatus(null))
  }

  useEffect(() => {
    refresh()
  }, [])

  const switchMode = async (mode) => {
    setLoading(true)
    setError(null)
    try {
      await setTradingMode(mode)
      refresh()
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Unable to change trading mode')
    } finally {
      setLoading(false)
    }
  }

  const mode = status?.trading_mode || 'paper'
  const isPaper = mode === 'paper'

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-widest text-slate-500">Trading mode</p>
          <h3 className="font-semibold text-lg">
            {isPaper ? 'Paper Trading' : 'Live Trading'}
          </h3>
          <p className="text-sm text-slate-400 mt-1">
            {isPaper
              ? 'Same live Angel One data as live mode — dummy orders in HK Quant, filled & marked from real quotes.'
              : 'Real orders via Angel One SmartAPI.'}
          </p>
        </div>
        <div className="flex rounded-lg border border-slate-700 overflow-hidden">
          <button
            type="button"
            disabled={loading || isPaper}
            onClick={() => switchMode('paper')}
            className={`px-4 py-2 text-sm font-medium ${
              isPaper ? 'bg-amber-500/20 text-amber-300' : 'bg-slate-950 text-slate-400 hover:bg-slate-800'
            }`}
          >
            Paper
          </button>
          <button
            type="button"
            disabled={loading || !isPaper}
            onClick={() => switchMode('live')}
            className={`px-4 py-2 text-sm font-medium ${
              !isPaper ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-950 text-slate-400 hover:bg-slate-800'
            }`}
          >
            Live
          </button>
        </div>
      </div>
      {status && (
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <span className={`px-2 py-1 rounded-full ${status.broker_connected ? 'bg-emerald-500/10 text-emerald-400' : 'bg-slate-800 text-slate-400'}`}>
            Broker {status.broker_connected ? 'connected' : 'not connected'}
          </span>
          <span className={`px-2 py-1 rounded-full ${status.can_trade ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
            {status.can_trade ? 'Trading enabled' : 'Trading blocked (risk)'}
          </span>
        </div>
      )}
      {error && <p className="mt-3 text-sm text-rose-400">{error}</p>}
    </section>
  )
}
