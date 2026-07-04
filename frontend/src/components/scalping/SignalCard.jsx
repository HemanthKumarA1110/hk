import { useState } from 'react'



/** Scalping signal card with AI quick-entry / tight-SL info. */

export default function SignalCard({ signal }) {

  const [open, setOpen] = useState(false)

  if (!signal) return null



  const isCall = signal.signal_type === 'CALL'

  const ind = signal.indicators || {}

  const ai = signal.ai || {}
  const validation = signal.entry_validation || ai.entry_validation || {}
  const verdictTone =
    validation.verdict === 'TAKE'
      ? 'bg-emerald-500/20 text-emerald-300'
      : validation.verdict === 'WAIT'
        ? 'bg-amber-500/20 text-amber-300'
        : 'bg-slate-700 text-slate-400'



  return (

    <div className="rounded-lg border border-slate-800 p-3 bg-slate-950/50">

      <div className="flex justify-between items-start gap-3">

        <div>

          <p className="text-xs text-slate-500">{new Date(signal.timestamp).toLocaleTimeString('en-IN')}</p>

          <p className={`font-semibold ${isCall ? 'text-emerald-400' : 'text-rose-400'}`}>

            {signal.signal_type} · {signal.option_symbol || signal.strike}

          </p>

          <p className="text-xs text-slate-500 mt-1">{signal.timeframe} · {signal.status}</p>

          {(signal.strategy_id || ind.strategy_id || ai.strategy_label) && (
            <p className="text-xs text-violet-400/90 mt-1">
              {signal.strategy_selection?.selected_label || ai.strategy_label || ind.strategy_id || signal.strategy_id}
              {ind.smc_bias && <span className="text-emerald-400/80"> · bias {ind.smc_bias}</span>}
            </p>
          )}

          {(signal.target_inr != null || ind.index_target_pts != null) && (

            <p className="text-xs text-cyan-400/90 mt-1">

              AI target ₹{Number(signal.target_inr ?? ai.target_inr ?? 0).toFixed(0)}

              {ind.index_target_pts != null && (

                <> · +{ind.index_target_pts} pts · SL −{ind.index_stop_pts} pts · {ind.max_hold_bars} bar max</>

              )}

            </p>

          )}

        </div>

        <div className="text-right text-sm font-mono">

          <p>₹{Number(signal.entry).toFixed(2)}</p>

          <p className="text-emerald-400">T {Number(signal.target).toFixed(2)}</p>

          <p className="text-rose-300">SL {Number(signal.stoploss).toFixed(2)}</p>

        </div>

      </div>

      {ai.action && (

        <div className="mt-2 pt-2 border-t border-slate-800 flex flex-wrap gap-2 items-center">

          <span

            className={`text-xs px-2 py-0.5 rounded ${

              ai.action === 'ENTER' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-700 text-slate-400'

            }`}

          >

            {ai.mode === 'adaptive_entry' ? 'Adaptive Entry' : ai.mode === 'quick_entry' ? 'Quick Entry' : ai.action} · {ai.confidence}%

          </span>

          {ai.regime && (

            <span className="text-xs px-2 py-0.5 rounded bg-violet-500/10 text-violet-300">{ai.regime}</span>

          )}

          {validation.verdict && (
            <span className={`text-xs px-2 py-0.5 rounded ${verdictTone}`}>
              Validator {validation.verdict} ({validation.score}/5)
            </span>
          )}

          <button type="button" onClick={() => setOpen(!open)} className="text-xs text-cyan-400 ml-auto">

            {open ? 'Hide' : 'AI reasoning'}

          </button>

          {open && <p className="text-xs text-slate-400 w-full mt-1">{ai.reasoning}</p>}

        </div>

      )}

    </div>

  )

}


