import { useCallback, useEffect, useState } from 'react'
import { fetchOrderStatus, fetchSwingSignals, fetchSwingStrategies, scanSwingPicks } from '../api'
import AngelOneAccountPanel from '../components/AngelOneAccountPanel'
import DeskBacktestModule from '../components/DeskBacktestModule'
import SwingAutoTradingPanel from '../components/SwingAutoTradingPanel'
import SwingStrategyPanel from '../components/SwingStrategyPanel'
import SwingOrderCell from '../components/SwingOrderCell'
import TradingModeToggle from '../components/TradingModeToggle'
import TradingViewChart from '../components/TradingViewChart'
import { useDeskBacktest } from '../hooks/useDeskBacktest'
import { filterStrategiesForDesk } from '../utils/strategyFilters'

function tvSymbol(symbol) {
  const base = (symbol || '').replace('-EQ', '').split('-')[0]
  return base ? `NSE:${base}` : 'NSE:RELIANCE'
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

export default function SwingPage() {
  const [payload, setPayload] = useState({ signals: [] })
  const [strategies, setStrategies] = useState([])
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(null)
  const [orderStatus, setOrderStatus] = useState(null)
  const backtest = useDeskBacktest('swing')

  const applyPayload = useCallback((data) => {
    const signals = data?.signals || []
    setPayload(data || { signals: [] })
    setSelected((prev) => prev || signals[0] || null)
  }, [])

  const load = useCallback(() => {
    fetchSwingSignals().then(applyPayload).catch(() => null)
  }, [applyPayload])

  useEffect(() => {
    load()
    fetchOrderStatus().then(setOrderStatus).catch(() => null)
    fetchSwingStrategies()
      .then((data) => setStrategies(filterStrategiesForDesk('swing', data?.strategies || [])))
      .catch(() => null)
  }, [load])

  const handleTradingModeChange = useCallback((status) => {
    setOrderStatus(status)
  }, [])

  const runScan = async () => {
    setScanning(true)
    setError('')
    try {
      const data = await scanSwingPicks()
      applyPayload(data)
    } catch (err) {
      setError(formatApiError(err, 'Swing scan failed. Please try again.'))
    } finally {
      setScanning(false)
    }
  }

  const signals = payload.signals || []
  const chartSymbol = selected ? tvSymbol(selected.symbol) : 'NSE:RELIANCE'
  const isPaper = orderStatus?.trading_mode === 'paper'
  const canTrade = orderStatus?.can_trade !== false

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-violet-400 text-xs uppercase tracking-widest">Swing Desk</p>
          <h2 className="text-3xl font-bold mt-1">Daily / Weekly Setups</h2>
          <p className="text-slate-400 mt-1">
            Top 10 Nifty 50 picks from Angel One daily history · 5–20% target logic
          </p>
          {payload.generated_at && (
            <p className="text-xs text-slate-500 mt-2">
              Last scan: {new Date(payload.generated_at).toLocaleString('en-IN')}
              {payload.source ? ` · ${payload.source}` : ''}
              {payload.history_loaded != null ? ` · ${payload.history_loaded} stocks with history` : ''}
            </p>
          )}
          {orderStatus && (
            <p className="text-xs mt-2 text-slate-500">
              Orders use {isPaper ? 'paper' : 'live'} · Delivery · Market
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={runScan}
          disabled={scanning}
          className="rounded-lg bg-violet-500 hover:bg-violet-400 text-slate-950 font-semibold px-5 py-2.5 disabled:opacity-50"
        >
          {scanning ? 'Scanning Nifty 50…' : 'Scan Top 10 Picks'}
        </button>
      </header>

      <div className="mb-6">
        <TradingModeToggle onChange={handleTradingModeChange} />
      </div>

      {error && <p className="text-rose-400 text-sm mb-4">{error}</p>}

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 mb-6 overflow-x-auto">
        <h3 className="font-semibold mb-3">Top 10 Swing Picks</h3>
        {signals.length === 0 && !scanning && (
          <p className="text-sm text-slate-500">
            No swing setups yet. Click <strong>Scan Top 10 Picks</strong> to analyse Nifty 50 using Angel One
            history.
          </p>
        )}
        {scanning && signals.length === 0 && (
          <p className="text-sm text-slate-400">Fetching daily candles from Angel One for Nifty 50 stocks…</p>
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
                    className={`border-b border-slate-800/80 ${isSelected ? 'bg-violet-500/10' : 'hover:bg-slate-800/40'}`}
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

      <SwingAutoTradingPanel strategies={strategies} isPaper={isPaper} />

      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <SwingStrategyPanel strategies={strategies} />
        <DeskBacktestModule
          engine="swing"
          accent="violet"
          title="Swing Strategy Backtest"
          defaultInterval="1d"
          strategies={strategies}
          backtest={backtest}
        />
      </div>

      <div className="mb-6">
        <TradingViewChart symbol={chartSymbol} interval="D" height={400} />
      </div>
    </div>
  )
}
