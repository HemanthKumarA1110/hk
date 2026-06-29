export default function TradeHistory({ trades = [] }) {
  if (!trades.length) {
    return (
      <div className="p-4 bg-white rounded-xl shadow-sm border border-slate-200">
        <h2 className="text-xl font-semibold mb-3">Recent Trades</h2>
        <p className="text-sm text-slate-500">No trades available yet.</p>
      </div>
    )
  }

  return (
    <div className="p-4 bg-white rounded-xl shadow-sm border border-slate-200">
      <h2 className="text-xl font-semibold mb-3">Recent Trades</h2>
      <div className="space-y-3 text-sm text-slate-600">
        {trades.slice(0, 5).map((trade, index) => (
          <div key={index} className="flex items-center justify-between gap-4 rounded-md bg-slate-50 p-3">
            <div>
              <p className="font-semibold">{trade.symbol}</p>
              <p>{trade.side} • {trade.status}</p>
            </div>
            <div className="text-right">
              <p>Qty {trade.qty}</p>
              <p>₹{trade.price.toFixed(2)}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
