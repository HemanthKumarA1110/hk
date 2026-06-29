export default function BrokerTradeFeed({ trades = [] }) {
  if (!trades.length) {
    return (
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="font-semibold mb-2">Trade Feed</h3>
        <p className="text-sm text-slate-500">No broker trades yet.</p>
      </section>
    )
  }

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <h3 className="font-semibold mb-3">Trade Feed</h3>
      <div className="space-y-2 max-h-80 overflow-auto">
        {trades.map((trade, index) => (
          <div key={trade.order_id || index} className="rounded-lg border border-slate-800 p-3 text-sm">
            <div className="flex justify-between gap-4">
              <div>
                <p className="font-medium">{trade.symbol}</p>
                <p className="text-slate-500">{trade.side} · {trade.status}</p>
              </div>
              <div className="text-right font-mono">
                <p>Qty {trade.qty}</p>
                <p>₹{Number(trade.price || 0).toFixed(2)}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
