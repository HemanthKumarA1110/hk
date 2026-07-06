import { useCallback, useEffect, useState } from 'react'
import { fetchIntradaySignals, fetchIntradayStrategies, fetchIntradayDesk, fetchOrderStatus, scanIntradayPicks } from '../api'
import AngelOneAccountPanel from '../components/AngelOneAccountPanel'
import DeskBacktestModule from '../components/DeskBacktestModule'
import IntradayAutoTradingPanel from '../components/IntradayAutoTradingPanel'
import IntradayStrategyPanel from '../components/IntradayStrategyPanel'
import SwingOrderCell from '../components/SwingOrderCell'
import TradingModeToggle from '../components/TradingModeToggle'
import TradingViewChart from '../components/TradingViewChart'
import { useDeskBacktest } from '../hooks/useDeskBacktest'
import { filterStrategiesForDesk } from '../utils/strategyFilters'

function tvSymbol(symbol) {
  const base = (symbol || '').replace('-EQ', '').split('-')[0]
  return base ? `NSE:${base}` : 'NSE:SBIN'
}

function formatApiError(err, fallback) {
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join('; ')
  if (detail && typeof detail === 'object') return detail.message || JSON.stringify(detail)
  if (err.code === 'ECONNABORTED') return 'Scan timed out. Please try again.'
  return err.message || fallback
}

function formatPrice(value) {
  if (value === null || value === undefined) return '—'
  return `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

const REFRESH_MS = 60_000

export default function IntradayPage() {
  const [payload, setPayload] = useState({ signals: [] })
  const [strategies, setStrategies] = useState([])
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(null)
  const [orderStatus, setOrderStatus] = useState(null)
  const [deskConfig, setDeskConfig] = useState(null)
  const backtest = useDeskBacktest('intraday')

  const applyPayload = useCallback((data) => {
    const signals = data?.signals || []
    setPayload(data || { signals: [] })
    setSelected((prev) => prev || signals[0] || null)
  }, [])

  const load = useCallback(async () => {
    try {
      const data = await fetchIntradaySignals()
      applyPayload(data)
      return data
    } catch {
      return null
    }
  }, [applyPayload])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const data = await load()
      if (cancelled || data?.signals?.length) return
      setScanning(true)
      setError('')
      try {
        const scanned = await scanIntradayPicks()
        if (!cancelled) applyPayload(scanned)
      } catch (err) {
        if (!cancelled) setError(formatApiError(err, 'Intraday scan failed. Please try again.'))
      } finally {
        if (!cancelled) setScanning(false)
      }
    })()
    fetchOrderStatus().then(setOrderStatus).catch(() => null)
    fetchIntradayDesk().then((d) => setDeskConfig(d?.config || null)).catch(() => null)
    fetchIntradayStrategies()
      .then((data) => setStrategies(filterStrategiesForDesk('intraday', data?.strategies || [])))
      .catch(() => null)
    return () => {
      cancelled = true
    }
  }, [applyPayload, load])

  useEffect(() => {
    const timer = setInterval(() => {
      if (!scanning) {
        load()
      }
    }, REFRESH_MS)
    return () => clearInterval(timer)
  }, [load, scanning])

  const handleTradingModeChange = useCallback((status) => {
    setOrderStatus(status)
  }, [])

  const runScan = async () => {
    setScanning(true)
    setError('')
    try {
      const data = await scanIntradayPicks()
      applyPayload(data)
    } catch (err) {
      setError(formatApiError(err, 'Intraday scan failed. Please try again.'))
    } finally {
      setScanning(false)
    }
  }

  const signals = payload.signals || []
  const chartSymbol = selected ? tvSymbol(selected.symbol) : 'NSE:SBIN'
  const isPaper = orderStatus?.trading_mode === 'paper'
  const canTrade = orderStatus?.can_trade !== false

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-cyan-400 text-xs uppercase tracking-widest">Intraday Desk</p>
          <h2 className="text-3xl font-bold mt-1">Live Intraday Setups</h2>
          <p className="text-slate-400 mt-1">
            ORB · VWAP trend · EMA+RSI · all positions exit by 3:15 PM IST · auto-refresh every 60s
          </p>
          {payload.generated_at && (
            <p className="text-xs text-slate-500 mt-2">
              Last scan: {new Date(payload.generated_at).toLocaleString('en-IN')}
              {payload.source ? ` · ${payload.source}` : ''}
              {payload.scan_hits != null ? ` · ${payload.scan_hits} scanner hits` : ''}
              {payload.universe_size != null ? ` · ${payload.universe_size} stocks screened` : ''}
              {payload.history_loaded != null ? ` · ${payload.history_loaded} live quotes` : ''}
              {payload.candles_loaded != null ? ` · ${payload.candles_loaded} with 5m history` : ''}
              {payload.min_score != null ? ` · min score ${payload.min_score}` : ''}
            </p>
          )}
          {orderStatus && (
            <p className="text-xs mt-2 text-slate-500">
              Orders use {isPaper ? 'paper' : 'live'} · Intraday · Market
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={runScan}
          disabled={scanning}
          className="rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold px-5 py-2.5 disabled:opacity-50"
        >
          {scanning ? 'Scanning live universe…' : 'Scan Top 10 Picks'}
        </button>
      </header>

      <div className="mb-6">
        <TradingModeToggle onChange={handleTradingModeChange} />
      </div>

      {error && <p className="text-rose-400 text-sm mb-4">{error}</p>}

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 mb-6 overflow-x-auto">
        <h3 className="font-semibold mb-3">Top 10 Intraday Picks</h3>
        {signals.length === 0 && !scanning && (
          <p className="text-sm text-slate-500">
            No intraday setups yet. Click <strong>Scan Top 10 Picks</strong> to fetch Angel One live quotes
            and 5m candles for Nifty 50 (takes up to 2 minutes).
            {payload.history_loaded === 0 && payload.generated_at ? (
              <span className="block mt-1 text-amber-400/90">
                Last scan had no live data — ensure broker is connected and run scan again during market hours.
              </span>
            ) : null}
          </p>
        )}
        {scanning && signals.length === 0 && (
          <p className="text-sm text-slate-400">
            Fetching Angel One live quotes and 5m candles for Nifty 50, then applying intraday filters…
          </p>
        )}
        {signals.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-800">
                <th className="py-2 pr-3">#</th>
                <th className="py-2 pr-3">Stock</th>
                <th className="py-2 pr-3">Signal</th>
                <th className="py-2 pr-3">Entry</th>
                <th className="py-2 pr-3">Target</th>
                <th className="py-2 pr-3">Stop Loss</th>
                <th className="py-2 pr-3">Score</th>
                <th className="py-2 pr-3">R:R</th>
                <th className="py-2">Place Order</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((signal, index) => {
                const target = signal.targets?.[0]
                const isSelected = selected?.symbol === signal.symbol
                return (
                  <tr
                    key={`${signal.symbol}-${index}`}
                    className={`border-b border-slate-800/80 ${isSelected ? 'bg-cyan-500/10' : 'hover:bg-slate-800/40'}`}
                  >
                    <td
                      className="py-3 pr-3 text-slate-400 cursor-pointer"
                      onClick={() => setSelected(signal)}
                    >
                      {index + 1}
                    </td>
                    <td
                      className="py-3 pr-3 font-semibold cursor-pointer"
                      onClick={() => setSelected(signal)}
                    >
                      {signal.symbol.replace('-EQ', '')}
                    </td>
                    <td
                      className={`py-3 pr-3 cursor-pointer ${signal.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}
                      onClick={() => setSelected(signal)}
                    >
                      {signal.side}
                    </td>
                    <td className="py-3 pr-3 font-mono cursor-pointer" onClick={() => setSelected(signal)}>
                      {formatPrice(signal.entry)}
                    </td>
                    <td
                      className="py-3 pr-3 font-mono text-emerald-400 cursor-pointer"
                      onClick={() => setSelected(signal)}
                    >
                      {formatPrice(target)}
                    </td>
                    <td
                      className="py-3 pr-3 font-mono text-rose-300 cursor-pointer"
                      onClick={() => setSelected(signal)}
                    >
                      {formatPrice(signal.stoploss)}
                    </td>
                    <td className="py-3 pr-3 cursor-pointer" onClick={() => setSelected(signal)}>
                      {Number(signal.score || 0).toFixed(0)}
                    </td>
                    <td className="py-3 pr-3 font-mono cursor-pointer" onClick={() => setSelected(signal)}>
                      {signal.risk_reward ?? '—'}
                    </td>
                    <td className="py-3">
                      <SwingOrderCell
                        signal={signal}
                        canTrade={canTrade}
                        isPaper={isPaper}
                        product="INTRADAY"
                        productLabel="Intraday · Market"
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>

      <AngelOneAccountPanel />

      <IntradayAutoTradingPanel strategies={strategies} isPaper={isPaper} />

      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <IntradayStrategyPanel strategies={strategies} />
        <DeskBacktestModule
          engine="intraday"
          accent="cyan"
          title="Intraday Strategy Backtest"
          defaultInterval="5m"
          strategies={strategies}
          backtest={backtest}
          deskCapital={deskConfig?.capital}
        />
      </div>

      <div className="mb-6">
        <TradingViewChart symbol={chartSymbol} interval="5" height={400} />
      </div>
    </div>
  )
}
