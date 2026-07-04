import { INSTRUMENT_META } from '../../types/scalping.types'



/**

 * Trade configuration panel — v3 quick scalp risk settings.

 */

export default function TradeConfigPanel({ instrument, config, onChange, optionLtp = 0, computedLots = 0 }) {

  const meta = INSTRUMENT_META[instrument]

  const lotSize = meta?.lotSize || config?.lot_size || 25

  const manualLots = optionLtp > 0 ? Math.floor(Number(config?.capital || 0) / (optionLtp * lotSize)) : computedLots

  const params = config?.params || {}

  const profile =

    instrument === 'banknifty'

      ? { target: 0.5, stop: 1.2, hold: 8 }

      : { target: 0.55, stop: 1.2, hold: 10 }



  const update = (key, value) => onChange({ ...config, [key]: value })



  return (

    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 space-y-4">

      <div>

        <p className="text-amber-400 text-xs uppercase tracking-widest">Configuration</p>

        <h3 className="font-semibold text-lg">Trade Settings</h3>

        <p className="text-xs text-slate-500 mt-1">

          {config?.strategy_label || 'AI Adaptive Scalp'} v{config?.strategy_version || 4}

        </p>

      </div>



      <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-3 text-xs text-slate-300 space-y-1">

        <p className="text-cyan-400 font-medium">v4 adaptive — AI picks strategy per bar</p>

        <p>4 strategies: Momentum · VWAP Bounce · Trend Follow · Volume Breakout</p>

        <p>Tighter filters: 2-bar confirm · EMA separation · session window</p>

        <p className="text-slate-500">Targets win rate over raw trade count</p>

      </div>



      <label className="block text-sm">

        <span className="text-slate-400">Capital Amount (INR)</span>

        <input

          type="number"

          value={config?.capital ?? 100000}

          onChange={(e) => update('capital', Number(e.target.value))}

          className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2"

        />

      </label>



      <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3 text-xs text-slate-300">

        <p className="text-emerald-400 font-medium">AI sets profit target per trade</p>

        <p className="mt-1">Based on momentum, ATR, and your daily risk budget (capital · max loss · trades left).</p>

      </div>



      <label className="block text-sm">

        <span className="text-slate-400">Max Loss Per Day (INR)</span>

        <input

          type="number"

          value={config?.max_loss_per_day ?? 5000}

          onChange={(e) => update('max_loss_per_day', Number(e.target.value))}

          className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2"

        />

      </label>



      <label className="block text-sm">

        <span className="text-slate-400">Max Trades Per Day (ceiling)</span>

        <input

          type="number"

          value={config?.max_trades_per_day ?? 5}

          onChange={(e) => update('max_trades_per_day', Number(e.target.value))}

          className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2"

        />

        <span className="text-xs text-slate-500 mt-1 block">Hard limit only — AI may stop earlier after 2–3 wins</span>

      </label>



      <div className="rounded-lg border border-slate-800 p-3 text-sm">

        <p className="text-slate-500 text-xs uppercase">Lot Quantity (auto)</p>

        <p className="text-2xl font-semibold mt-1">{Math.max(manualLots, 0)} lots</p>

        <p className="text-xs text-slate-500 mt-1">

          Lot size {lotSize} · Option LTP ₹{Number(optionLtp).toFixed(2)}

        </p>

      </div>



      <div>

        <p className="text-slate-400 text-sm mb-2">Timeframe</p>

        <div className="flex gap-2">

          {['1m', '3m'].map((tf) => (

            <button

              key={tf}

              type="button"

              onClick={() => update('timeframe', tf)}

              className={`flex-1 rounded-lg py-2 text-sm font-medium ${

                config?.timeframe === tf

                  ? 'bg-amber-500 text-slate-950'

                  : 'border border-slate-700 text-slate-400'

              }`}

            >

              {tf}

            </button>

          ))}

        </div>

      </div>

    </section>

  )

}


