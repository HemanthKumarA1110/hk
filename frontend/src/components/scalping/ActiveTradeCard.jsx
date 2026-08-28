/** Active trade tracker — v3 quick exit monitoring. */

export default function ActiveTradeCard({ trade, onEmergencyClose, closing = false }) {

  if (!trade) return null

  const pnl = trade.unrealized_pnl ?? 0

  const aiExit = trade.ai_exit

  const barsLeft = Math.max(0, (trade.max_hold_bars || 10) - (trade.bars_held || 0))



  return (

    <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3">

      <div className="flex justify-between items-start">

        <div>

          <p className="font-semibold">{trade.signal_type} · {trade.option_symbol}</p>

          <p className="text-xs text-slate-500">

            Entry spot {Number(trade.entry_spot || trade.entry).toFixed(1)}

            {trade.target_pts != null && ` · T +${trade.target_pts} / SL −${trade.stop_pts}`}

          </p>

          {aiExit?.action === 'EXIT' && (

            <span className="text-xs bg-rose-500/20 text-rose-300 px-2 py-0.5 rounded mt-1 inline-block">

              AI: {aiExit.mode || 'quick exit'} — {aiExit.reasoning}

            </span>

          )}

        </div>

        <div className="text-right font-mono text-sm">

          <p>Spot {Number(trade.current_ltp || trade.entry_spot || trade.entry).toFixed(1)}</p>

          <p className={pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}>P&L ₹{Number(pnl).toFixed(2)}</p>

        </div>

      </div>

      <div className="flex flex-wrap gap-3 text-xs text-slate-500 mt-2">

        <span>Premium T ₹{Number(trade.target).toFixed(2)}</span>

        <span>SL ₹{Number(trade.stoploss).toFixed(2)}</span>

        <span>{trade.bars_held ?? 0}/{trade.max_hold_bars ?? 10} bars</span>

        <span>{barsLeft} bars to time exit</span>

      </div>

      <div className="mt-3 flex justify-end">
        <button
          type="button"
          onClick={() => onEmergencyClose?.(trade)}
          disabled={closing}
          className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-xs font-semibold text-rose-300 hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {closing ? 'Closing…' : 'Emergency Close'}
        </button>
      </div>

    </div>

  )

}


