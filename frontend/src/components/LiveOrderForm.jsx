import { useEffect, useState } from 'react'
import { evaluateRiskTrade, fetchOrderStatus, placeOrder } from '../api'

export default function LiveOrderForm({ onPlaced, orderStatus: externalStatus }) {
  const [form, setForm] = useState({
    symbol: 'RELIANCE-EQ',
    exchange: 'NSE',
    side: 'BUY',
    qty: 1,
    price: 0,
    order_type: 'MARKET',
    product: 'INTRADAY',
    stoploss: 0,
  })
  const [riskPreview, setRiskPreview] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [orderStatus, setOrderStatus] = useState(externalStatus || null)

  useEffect(() => {
    if (externalStatus) {
      setOrderStatus(externalStatus)
      return
    }
    fetchOrderStatus().then(setOrderStatus).catch(() => null)
  }, [externalStatus])

  const isPaper = orderStatus?.trading_mode === 'paper'
  const canSubmit = orderStatus?.can_trade !== false

  const previewRisk = async () => {
    const entry = form.price || 1000
    const stoploss = form.stoploss || entry * 0.995
    try {
      const data = await evaluateRiskTrade({ entry, stoploss, side: form.side })
      setRiskPreview(data)
    } catch {
      setRiskPreview(null)
    }
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const payload = {
        ...form,
        stoploss: form.stoploss > 0 ? form.stoploss : undefined,
      }
      const data = await placeOrder(payload)
      setResult(data)
      onPlaced?.(data)
    } catch (err) {
      const message = err.response?.data?.detail || 'Unable to submit order'
      setError(typeof message === 'string' ? message : JSON.stringify(message))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <div>
          <p className={`text-xs uppercase tracking-widest ${isPaper ? 'text-amber-400' : 'text-emerald-400'}`}>
            {isPaper ? 'Paper Trading' : 'Live Trading'}
          </p>
          <h3 className="font-semibold text-lg">Place Order</h3>
        </div>
        {orderStatus && (
          <span
            className={`text-xs px-2 py-1 rounded-full ${
              canSubmit ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'
            }`}
          >
            {canSubmit ? (isPaper ? 'Paper OK' : 'Risk OK') : 'Trading Blocked'}
          </span>
        )}
      </div>

      {isPaper && (
        <p className="mb-4 text-xs text-amber-200/80 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
          Paper mode uses simulated instant fills and demo/reference prices when live quotes are unavailable.
          Connect Angel One only when you switch to live trading.
        </p>
      )}

      <form className="space-y-3" onSubmit={handleSubmit}>
        <div className="grid gap-3 sm:grid-cols-2">
          <input
            value={form.symbol}
            onChange={(e) => setForm({ ...form, symbol: e.target.value })}
            placeholder="Symbol (RELIANCE-EQ)"
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
          <select
            value={form.side}
            onChange={(e) => setForm({ ...form, side: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          >
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <input
            type="number"
            min="1"
            value={form.qty}
            onChange={(e) => setForm({ ...form, qty: Number(e.target.value) })}
            placeholder="Qty"
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
          <select
            value={form.order_type}
            onChange={(e) => setForm({ ...form, order_type: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          >
            <option value="MARKET">MARKET</option>
            <option value="LIMIT">LIMIT</option>
          </select>
          <select
            value={form.product}
            onChange={(e) => setForm({ ...form, product: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          >
            <option value="INTRADAY">INTRADAY</option>
            <option value="DELIVERY">DELIVERY</option>
          </select>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <input
            type="number"
            min="0"
            step="0.05"
            value={form.price}
            onChange={(e) => setForm({ ...form, price: Number(e.target.value) })}
            placeholder={isPaper ? 'Price (0 = reference/demo LTP)' : 'Limit price (0 = market LTP)'}
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
          <input
            type="number"
            min="0"
            step="0.05"
            value={form.stoploss}
            onChange={(e) => setForm({ ...form, stoploss: Number(e.target.value) })}
            placeholder="Stoploss (optional, for risk check)"
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={previewRisk}
            className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800"
          >
            Preview Risk
          </button>
          <button
            type="submit"
            disabled={loading || !canSubmit}
            className={`rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50 ${
              isPaper
                ? 'bg-amber-500 hover:bg-amber-400 text-slate-950'
                : 'bg-emerald-500 hover:bg-emerald-400 text-slate-950'
            }`}
          >
            {loading ? 'Submitting...' : isPaper ? 'Submit Paper Order' : 'Submit Live Order'}
          </button>
        </div>
      </form>

      {riskPreview && (
        <div className="mt-3 rounded-lg bg-slate-950/50 p-3 text-xs text-slate-400">
          Risk approved: {riskPreview.approved ? 'Yes' : 'No'} · Suggested qty:{' '}
          {riskPreview.position_size?.qty ?? '—'} · {riskPreview.reason}
        </div>
      )}
      {error && <p className="mt-3 text-sm text-rose-400">{error}</p>}
      {result && (
        <div className={`mt-3 rounded-lg border p-3 text-sm ${
          isPaper ? 'bg-amber-500/10 border-amber-500/20' : 'bg-emerald-500/10 border-emerald-500/20'
        }`}>
          <p className={`font-medium ${isPaper ? 'text-amber-300' : 'text-emerald-400'}`}>
            Order {result.status}
          </p>
          <p className="text-slate-300">ID: {result.broker_order_id || result.id}</p>
          <p className="text-slate-400">{result.message}</p>
        </div>
      )}
    </section>
  )
}
