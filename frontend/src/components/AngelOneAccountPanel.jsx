import { useCallback, useEffect, useState } from 'react'
import { cancelBrokerOrder, fetchBrokerAccount } from '../api'

const TABS = [
  { id: 'orders', label: 'Orders' },
  { id: 'positions', label: 'Positions' },
  { id: 'holdings', label: 'Holdings' },
  { id: 'trades', label: 'Trade History' },
]

function formatMoney(value) {
  if (value === null || value === undefined) return '—'
  return `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

function formatTime(value) {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('en-IN')
}

function EmptyRow({ message, colSpan = 9 }) {
  return (
    <tr>
      <td colSpan={colSpan} className="py-6 text-center text-sm text-slate-500">
        {message}
      </td>
    </tr>
  )
}

export default function AngelOneAccountPanel() {
  const [tab, setTab] = useState('orders')
  const [snapshot, setSnapshot] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [cancellingId, setCancellingId] = useState('')
  const [actionMessage, setActionMessage] = useState('')
  const [actionError, setActionError] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await fetchBrokerAccount()
      setSnapshot(data)
      if (!data.connected && data.message) {
        setError(data.message)
      }
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Unable to load Angel One account data')
      setSnapshot(null)
    } finally {
      setLoading(false)
    }
  }, [])

  const handleCancel = async (row) => {
    if (!row.order_id || !row.cancellable) return
    const remainingQty = Math.max(0, Number(row.qty || 0) - Number(row.filled_qty || 0))
    const qtyLabel = remainingQty > 0 ? remainingQty : row.qty
    const confirmed = window.confirm(
      `Cancel ${row.side} ${qtyLabel} x ${row.symbol} (${row.order_type || 'ORDER'}) on Angel One?`
    )
    if (!confirmed) return

    setCancellingId(row.order_id)
    setActionMessage('')
    setActionError(false)
    try {
      const result = await cancelBrokerOrder(row.order_id, row.cancel_variety || row.variety || 'NORMAL')
      setActionMessage(result.message || `Order ${row.order_id} cancelled`)
      setActionError(false)
      await load()
    } catch (err) {
      const detail = err.response?.data?.detail
      setActionMessage(typeof detail === 'string' ? detail : 'Unable to cancel order')
      setActionError(true)
    } finally {
      setCancellingId('')
    }
  }

  useEffect(() => {
    load()
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [load])

  const orders = snapshot?.orders || []
  const positions = snapshot?.positions || []
  const holdings = snapshot?.holdings || []
  const trades = snapshot?.trades || []

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 mb-6">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <p className="text-xs uppercase tracking-widest text-slate-500">Angel One Account</p>
          <h3 className="font-semibold text-lg">Orders, Positions & History</h3>
          {snapshot?.fetched_at && (
            <p className="text-xs text-slate-500 mt-1">
              Last synced: {formatTime(snapshot.fetched_at)}
              {snapshot.connected ? ' · Live from broker' : ' · Not connected'}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
        >
          {loading ? 'Syncing…' : 'Refresh'}
        </button>
      </div>

      {error && !snapshot?.connected && (
        <p className="text-sm text-amber-400 mb-4">{error}</p>
      )}
      {actionMessage && (
        <p className={`text-sm mb-4 ${actionError ? 'text-rose-400' : 'text-emerald-400'}`}>{actionMessage}</p>
      )}

      <div className="flex flex-wrap gap-2 mb-4">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            className={`rounded-lg px-3 py-1.5 text-sm ${
              tab === item.id
                ? 'bg-violet-500 text-slate-950 font-semibold'
                : 'border border-slate-700 text-slate-400 hover:bg-slate-800'
            }`}
          >
            {item.label}
            {item.id === 'orders' && ` (${orders.length})`}
            {item.id === 'positions' && ` (${positions.length})`}
            {item.id === 'holdings' && ` (${holdings.length})`}
            {item.id === 'trades' && ` (${trades.length})`}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto">
        {tab === 'orders' && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-800">
                <th className="py-2 pr-3">Symbol</th>
                <th className="py-2 pr-3">Side</th>
                <th className="py-2 pr-3">Qty</th>
                <th className="py-2 pr-3">Filled</th>
                <th className="py-2 pr-3">Price</th>
                <th className="py-2 pr-3">Product</th>
                <th className="py-2 pr-3">Type</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Updated</th>
                <th className="py-2">Action</th>
              </tr>
            </thead>
            <tbody>
              {orders.length === 0 && (
                <EmptyRow message={loading ? 'Loading orders…' : 'No orders in Angel One order book.'} />
              )}
              {orders.map((row) => (
                <tr key={`${row.order_id}-${row.symbol}-${row.updated_at}`} className="border-b border-slate-800/80">
                  <td className="py-2 pr-3 font-medium">{row.symbol}</td>
                  <td className={`py-2 pr-3 ${row.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>{row.side}</td>
                  <td className="py-2 pr-3">{row.qty}</td>
                  <td className="py-2 pr-3">{row.filled_qty}</td>
                  <td className="py-2 pr-3 font-mono">{formatMoney(row.price)}</td>
                  <td className="py-2 pr-3">{row.product}</td>
                  <td className="py-2 pr-3">{row.order_type || '—'}</td>
                  <td className="py-2 pr-3">{row.status}</td>
                  <td className="py-2 pr-3 text-xs text-slate-400">{formatTime(row.updated_at)}</td>
                  <td className="py-2">
                    {row.cancellable ? (
                      <button
                        type="button"
                        onClick={() => handleCancel(row)}
                        disabled={cancellingId === row.order_id}
                        className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-2.5 py-1 text-xs font-semibold text-rose-300 hover:bg-rose-500/20 disabled:opacity-50"
                      >
                        {cancellingId === row.order_id ? '…' : 'Cancel'}
                      </button>
                    ) : (
                      <span className="text-xs text-slate-600">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {tab === 'positions' && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-800">
                <th className="py-2 pr-3">Symbol</th>
                <th className="py-2 pr-3">Qty</th>
                <th className="py-2 pr-3">Avg Price</th>
                <th className="py-2 pr-3">LTP</th>
                <th className="py-2 pr-3">P&L</th>
                <th className="py-2">Product</th>
              </tr>
            </thead>
            <tbody>
              {positions.length === 0 && (
                <EmptyRow message={loading ? 'Loading positions…' : 'No open day positions in Angel One.'} />
              )}
              {positions.map((row) => (
                <tr key={`${row.symbol}-${row.product}`} className="border-b border-slate-800/80">
                  <td className="py-2 pr-3 font-medium">{row.symbol}</td>
                  <td className="py-2 pr-3">{row.qty}</td>
                  <td className="py-2 pr-3 font-mono">{formatMoney(row.avg_price)}</td>
                  <td className="py-2 pr-3 font-mono">{formatMoney(row.ltp)}</td>
                  <td className={`py-2 pr-3 font-mono ${row.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {formatMoney(row.pnl)}
                  </td>
                  <td className="py-2">{row.product}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {tab === 'holdings' && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-800">
                <th className="py-2 pr-3">Symbol</th>
                <th className="py-2 pr-3">Qty</th>
                <th className="py-2 pr-3">Avg Price</th>
                <th className="py-2 pr-3">LTP</th>
                <th className="py-2 pr-3">Value</th>
                <th className="py-2">P&L</th>
              </tr>
            </thead>
            <tbody>
              {holdings.length === 0 && (
                <EmptyRow message={loading ? 'Loading holdings…' : 'No delivery holdings in Angel One.'} />
              )}
              {holdings.map((row) => (
                <tr key={`${row.symbol}-holding`} className="border-b border-slate-800/80">
                  <td className="py-2 pr-3 font-medium">{row.symbol}</td>
                  <td className="py-2 pr-3">{row.qty}</td>
                  <td className="py-2 pr-3 font-mono">{formatMoney(row.avg_price)}</td>
                  <td className="py-2 pr-3 font-mono">{formatMoney(row.ltp)}</td>
                  <td className="py-2 pr-3 font-mono">{formatMoney(row.current_value)}</td>
                  <td className={`py-2 font-mono ${row.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {formatMoney(row.pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {tab === 'trades' && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-800">
                <th className="py-2 pr-3">Symbol</th>
                <th className="py-2 pr-3">Side</th>
                <th className="py-2 pr-3">Qty</th>
                <th className="py-2 pr-3">Price</th>
                <th className="py-2 pr-3">Product</th>
                <th className="py-2 pr-3">Order ID</th>
                <th className="py-2">Time</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 && (
                <EmptyRow message={loading ? 'Loading trade history…' : 'No executed trades in Angel One trade book.'} />
              )}
              {trades.map((row) => (
                <tr key={`${row.trade_id}-${row.timestamp}`} className="border-b border-slate-800/80">
                  <td className="py-2 pr-3 font-medium">{row.symbol}</td>
                  <td className={`py-2 pr-3 ${row.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>{row.side}</td>
                  <td className="py-2 pr-3">{row.qty}</td>
                  <td className="py-2 pr-3 font-mono">{formatMoney(row.price)}</td>
                  <td className="py-2 pr-3">{row.product}</td>
                  <td className="py-2 pr-3 text-xs text-slate-400">{row.order_id || '—'}</td>
                  <td className="py-2 text-xs text-slate-400">{formatTime(row.timestamp)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}
