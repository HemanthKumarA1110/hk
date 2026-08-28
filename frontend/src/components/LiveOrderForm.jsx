import { useEffect, useMemo, useState } from 'react'
import { evaluateRiskTrade, fetchOrderStatus, placeOrder } from '../api'
import SymbolLookupInput from './SymbolLookupInput'

const TRADE_STYLES = [
  { id: 'intraday', label: 'Intraday', product: 'INTRADAY', hint: 'MIS · same-day square-off' },
  { id: 'swing', label: 'Swing / Delivery', product: 'DELIVERY', hint: 'CNC · multi-day hold' },
]

function calcQtyFromAmount(amount, price) {
  if (!amount || !price || price <= 0) return 0
  return Math.max(1, Math.floor(amount / price))
}

export default function LiveOrderForm({ onPlaced, orderStatus: externalStatus }) {
  const [form, setForm] = useState({
    symbol: 'RELIANCE-EQ',
    symboltoken: '',
    exchange: 'NSE',
    side: 'BUY',
    qty: 1,
    price: 0,
    order_type: 'MARKET',
    product: 'INTRADAY',
    stoploss: 0,
  })
  const [sizeMode, setSizeMode] = useState('qty')
  const [amount, setAmount] = useState(10000)
  const [tradeStyle, setTradeStyle] = useState('intraday')
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

  const canSubmit = orderStatus?.can_trade !== false
  const effectivePrice = form.order_type === 'LIMIT' && form.price > 0 ? form.price : form.price

  const computedQty = useMemo(() => {
    if (sizeMode === 'qty') return form.qty
    return calcQtyFromAmount(amount, effectivePrice || form.price)
  }, [sizeMode, form.qty, amount, effectivePrice, form.price])

  const orderValue = useMemo(() => {
    const px = effectivePrice > 0 ? effectivePrice : 0
    if (!px || !computedQty) return null
    return px * computedQty
  }, [effectivePrice, computedQty])

  useEffect(() => {
    if (sizeMode === 'amount' && computedQty > 0 && computedQty !== form.qty) {
      setForm((prev) => ({ ...prev, qty: computedQty }))
    }
  }, [sizeMode, computedQty, form.qty])

  const applyTradeStyle = (styleId) => {
    const style = TRADE_STYLES.find((s) => s.id === styleId)
    setTradeStyle(styleId)
    if (style) {
      setForm((prev) => ({ ...prev, product: style.product }))
    }
  }

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

    const qty = sizeMode === 'amount' ? computedQty : form.qty
    if (sizeMode === 'amount' && (!effectivePrice || effectivePrice <= 0)) {
      setError('Enter a limit price to calculate quantity from amount, or switch to Qty mode.')
      setLoading(false)
      return
    }
    if (qty < 1) {
      setError('Quantity must be at least 1.')
      setLoading(false)
      return
    }

    try {
      const payload = {
        ...form,
        qty,
        stoploss: form.stoploss > 0 ? form.stoploss : undefined,
        symboltoken: form.symboltoken || undefined,
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
          <p className="text-xs uppercase tracking-widest text-emerald-400">
            Live Trading
          </p>
          <h3 className="font-semibold text-lg">Place Order</h3>
          <p className="text-xs text-slate-500 mt-0.5">Broker-style entry · stock search · qty or amount</p>
        </div>
        {orderStatus && (
          <span
            className={`text-xs px-2 py-1 rounded-full ${
              canSubmit ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'
            }`}
          >
            {canSubmit ? 'Risk OK' : 'Trading Blocked'}
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        {TRADE_STYLES.map((style) => (
          <button
            key={style.id}
            type="button"
            onClick={() => applyTradeStyle(style.id)}
            className={`rounded-lg px-3 py-2 text-left text-sm border ${
              tradeStyle === style.id
                ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
                : 'border-slate-700 text-slate-400 hover:bg-slate-800'
            }`}
          >
            <span className="font-medium block">{style.label}</span>
            <span className="text-[10px] text-slate-500">{style.hint}</span>
          </button>
        ))}
      </div>

      <form className="space-y-3" onSubmit={handleSubmit}>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm sm:col-span-1">
            <span className="text-slate-400 text-xs">Stock / Symbol</span>
            <div className="mt-1">
              <SymbolLookupInput
                value={form.symbol}
                exchange={form.exchange}
                placeholder="Search e.g. RELIANCE, TCS"
                onChange={(sym) => setForm((prev) => ({ ...prev, symbol: sym }))}
                onSelect={(hit) =>
                  setForm((prev) => ({
                    ...prev,
                    symbol: hit.symbol,
                    symboltoken: hit.token || '',
                    exchange: hit.exchange || 'NSE',
                  }))
                }
              />
            </div>
          </label>
          <label className="block text-sm">
            <span className="text-slate-400 text-xs">Side</span>
            <div className="flex gap-2 mt-1">
              {['BUY', 'SELL'].map((side) => (
                <button
                  key={side}
                  type="button"
                  onClick={() => setForm((prev) => ({ ...prev, side }))}
                  className={`flex-1 rounded-lg py-2 text-sm font-semibold ${
                    form.side === side
                      ? side === 'BUY'
                        ? 'bg-emerald-500 text-slate-950'
                        : 'bg-rose-500 text-white'
                      : 'border border-slate-700 text-slate-400'
                  }`}
                >
                  {side}
                </button>
              ))}
            </div>
          </label>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3 space-y-3">
          <div className="flex gap-2">
            {[
              ['qty', 'Quantity'],
              ['amount', 'Amount (₹)'],
            ].map(([mode, label]) => (
              <button
                key={mode}
                type="button"
                onClick={() => setSizeMode(mode)}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium ${
                  sizeMode === mode
                    ? 'bg-slate-700 text-slate-100'
                    : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {sizeMode === 'qty' ? (
            <label className="block text-sm">
              <span className="text-slate-400 text-xs">Quantity (shares)</span>
              <input
                type="number"
                min="1"
                value={form.qty}
                onChange={(e) => setForm((prev) => ({ ...prev, qty: Number(e.target.value) }))}
                className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              />
            </label>
          ) : (
            <label className="block text-sm">
              <span className="text-slate-400 text-xs">Order amount (₹)</span>
              <input
                type="number"
                min="1"
                step="100"
                value={amount}
                onChange={(e) => setAmount(Number(e.target.value))}
                className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              />
              <p className="text-xs text-slate-500 mt-1">
                {effectivePrice > 0 ? (
                  <>
                    ≈ <span className="text-slate-300 font-medium">{computedQty}</span> shares
                    {orderValue != null && ` · ₹${orderValue.toLocaleString('en-IN')}`}
                  </>
                ) : (
                  'Enter limit price below to auto-calculate quantity from amount.'
                )}
              </p>
            </label>
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block text-sm">
            <span className="text-slate-400 text-xs">Order type</span>
            <select
              value={form.order_type}
              onChange={(e) => setForm((prev) => ({ ...prev, order_type: e.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            >
              <option value="MARKET">MARKET</option>
              <option value="LIMIT">LIMIT</option>
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-slate-400 text-xs">Product</span>
            <select
              value={form.product}
              onChange={(e) => setForm((prev) => ({ ...prev, product: e.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            >
              <option value="INTRADAY">INTRADAY (MIS)</option>
              <option value="DELIVERY">DELIVERY (CNC)</option>
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-slate-400 text-xs">Exchange</span>
            <select
              value={form.exchange}
              onChange={(e) => setForm((prev) => ({ ...prev, exchange: e.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            >
              <option value="NSE">NSE</option>
              <option value="BSE">BSE</option>
            </select>
          </label>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="text-slate-400 text-xs">
              {form.order_type === 'LIMIT' ? 'Limit price (₹)' : 'Price (₹) — 0 for market LTP'}
            </span>
            <input
              type="number"
              min="0"
              step="0.05"
              value={form.price}
              onChange={(e) => setForm((prev) => ({ ...prev, price: Number(e.target.value) }))}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-400 text-xs">Stoploss (optional, for risk check)</span>
            <input
              type="number"
              min="0"
              step="0.05"
              value={form.stoploss}
              onChange={(e) => setForm((prev) => ({ ...prev, stoploss: Number(e.target.value) }))}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            />
          </label>
        </div>

        {sizeMode === 'qty' && orderValue != null && effectivePrice > 0 && (
          <p className="text-xs text-slate-500">
            Order value ≈ ₹{orderValue.toLocaleString('en-IN')} ({form.qty} × ₹{effectivePrice})
          </p>
        )}

        <div className="flex flex-wrap gap-2 pt-1">
          <button
            type="button"
            onClick={previewRisk}
            className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800"
          >
            Preview risk
          </button>
          <button
            type="submit"
            disabled={loading || !canSubmit}
            className={`rounded-lg px-5 py-2 text-sm font-semibold disabled:opacity-50 ${
              form.side === 'BUY'
                ? 'bg-emerald-500 hover:bg-emerald-400 text-slate-950'
                : 'bg-rose-500 hover:bg-rose-400 text-white'
            }`}
          >
            {loading
              ? 'Submitting…'
              : `${form.side} ${computedQty || form.qty} · Live`}
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
        <div
          className="mt-3 rounded-lg border p-3 text-sm bg-emerald-500/10 border-emerald-500/20"
        >
          <p className="font-medium text-emerald-400">
            Order {result.status}
          </p>
          <p className="text-slate-300">ID: {result.broker_order_id || result.id}</p>
          <p className="text-slate-400">{result.message}</p>
        </div>
      )}
    </section>
  )
}
