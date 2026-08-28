import { useState } from 'react'
import { placeOrder } from '../api'

function orderSymbol(symbol) {
  const value = (symbol || '').trim()
  if (!value) return ''
  if (value.includes('-')) return value
  return `${value}-EQ`
}

function formatApiError(err) {
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join('; ')
  return err.message || 'Order failed'
}

function formatAmount(value) {
  return `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

export default function SwingOrderCell({
  signal,
  canTrade,
  onPlaced,
  product = 'DELIVERY',
  productLabel = 'Delivery · Market',
}) {
  const [side, setSide] = useState(signal.side || 'BUY')
  const [qty, setQty] = useState(1)
  const [loading, setLoading] = useState(false)
  const [feedback, setFeedback] = useState(null)
  const entryPrice = Number(signal.entry) || 0
  const orderAmount = entryPrice * qty

  const handlePlace = async (event) => {
    event.stopPropagation()
    if (!canTrade || qty < 1) return

    setLoading(true)
    setFeedback(null)
    try {
      const data = await placeOrder({
        symbol: orderSymbol(signal.symbol),
        symboltoken: signal.token ? String(signal.token) : undefined,
        exchange: 'NSE',
        side,
        qty: Number(qty),
        order_type: 'MARKET',
        product,
        price: Number(signal.entry) || 0,
        stoploss: signal.stoploss > 0 ? signal.stoploss : undefined,
      })
      setFeedback({ type: 'success', text: `Order ${data.status} · ${data.broker_order_id || data.id}` })
      onPlaced?.(data)
    } catch (err) {
      setFeedback({ type: 'error', text: formatApiError(err) })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-w-[220px]" onClick={(event) => event.stopPropagation()}>
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg border border-slate-700 overflow-hidden text-xs">
          <button
            type="button"
            onClick={() => setSide('BUY')}
            className={`px-2.5 py-1.5 font-semibold ${side === 'BUY' ? 'bg-emerald-500 text-slate-950' : 'text-slate-400 hover:bg-slate-800'}`}
          >
            BUY
          </button>
          <button
            type="button"
            onClick={() => setSide('SELL')}
            className={`px-2.5 py-1.5 font-semibold ${side === 'SELL' ? 'bg-rose-500 text-slate-950' : 'text-slate-400 hover:bg-slate-800'}`}
          >
            SELL
          </button>
        </div>
        <div className="flex flex-col">
          <input
            type="number"
            min="1"
            value={qty}
            onChange={(event) => setQty(Math.max(1, Number(event.target.value) || 1))}
            className="w-16 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs"
            aria-label="Quantity"
          />
          <span className="text-[10px] text-slate-400 mt-0.5 w-16 text-center font-mono">
            {formatAmount(orderAmount)}
          </span>
        </div>
        <button
          type="button"
          onClick={handlePlace}
          disabled={loading || !canTrade || qty < 1}
          className="rounded-lg bg-violet-500 hover:bg-violet-400 text-slate-950 px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
        >
          {loading ? '…' : 'Place'}
        </button>
      </div>
      <p className="text-[10px] text-slate-500 mt-1">{productLabel}</p>
      {feedback && (
        <p className={`text-[10px] mt-1 ${feedback.type === 'success' ? 'text-emerald-400' : 'text-rose-400'}`}>
          {feedback.text}
        </p>
      )}
      {!canTrade && (
        <p className="text-[10px] text-rose-400 mt-1">
          Connect Angel One before placing live orders
        </p>
      )}
    </div>
  )
}
