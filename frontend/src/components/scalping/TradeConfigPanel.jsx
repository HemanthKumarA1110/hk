import { INSTRUMENT_META } from '../../types/scalping.types'

/** Trade configuration — long CE/PE buys sized from deployable capital. */
export default function TradeConfigPanel({
  instrument,
  config,
  onChange,
  optionLtp = 0,
  computedLots = 0,
  capitalInfo = null,
  positionSizing = null,
}) {
  const meta = INSTRUMENT_META[instrument]
  const lotSize = meta?.lotSize || config?.lot_size || 65
  const isIndexDesk = instrument === 'nifty50' || instrument === 'banknifty'
  const autoBroker = Boolean(config?.auto_capital_from_broker ?? true)
  const liveSession = Number(capitalInfo?.session_start_capital)
  const liveBroker = Number(capitalInfo?.broker_available_cash)
  const usingBroker = autoBroker && (capitalInfo?.session_capital_source === 'broker' || Number.isFinite(liveBroker))
  const deployable = Number(
    capitalInfo?.deployable_capital ?? (usingBroker && Number.isFinite(liveSession) ? liveSession : config?.capital ?? 0)
  )
  const premium = Number(optionLtp || positionSizing?.option_premium || 0)
  const utilizationLots =
    premium > 0 ? Math.floor(deployable / (premium * lotSize)) : Number(computedLots || positionSizing?.lots || 0)
  const displayLots = Math.max(utilizationLots, 0)

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

      {isIndexDesk && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-slate-300 space-y-2">
          <p className="text-amber-300 font-medium">Option buy only · CE on CALL · PE on PUT</p>
          <p>
            Entries are always long options (BUY CE or BUY PE). Exits square off the same contract — no
            option writing.             Each entry uses up to {(Number(config?.capital_utilization_pct ?? 1) * 100).toFixed(0)}% of deployable
            capital. Intraday profits credit T+1 — sizing keeps session-start capital minus today&apos;s losses.
          </p>
          {capitalInfo?.session_start_capital != null && (
            <div className="grid grid-cols-2 gap-2 pt-1">
              <div>
                <p className="text-slate-500">Session capital</p>
                <p className="font-mono text-slate-200">
                  ₹{Number(capitalInfo.session_start_capital).toLocaleString('en-IN')}
                </p>
                <p className="text-[10px] text-slate-500 capitalize">
                  {capitalInfo.session_capital_source === 'broker'
                    ? 'Angel One margin'
                    : autoBroker
                      ? 'fallback — broker cash not received yet'
                      : 'manual'}
                </p>
              </div>
              <div>
                <p className="text-slate-500">Deployable now</p>
                <p className="font-mono text-emerald-300">
                  ₹{Number(capitalInfo.deployable_capital ?? 0).toLocaleString('en-IN')}
                </p>
                {capitalInfo.daily_pnl !== 0 && (
                  <p className="text-[10px] text-slate-500">Today P&L ₹{Number(capitalInfo.daily_pnl).toLocaleString('en-IN')}</p>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-3 text-xs text-slate-300 space-y-1">
        <p className="text-cyan-400 font-medium">v4 adaptive — AI picks strategy per bar</p>
        <p>4 strategies: Momentum · VWAP Bounce · Trend Follow · Volume Breakout</p>
        <p>Battle session: 09:20–10:30 · 13:30–14:45 IST (Mon–Fri)</p>
        <p className="text-slate-500">Targets win rate over raw trade count</p>
      </div>

      {isIndexDesk && (
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={autoBroker}
            onChange={(e) => update('auto_capital_from_broker', e.target.checked)}
            className="rounded border-slate-600"
          />
          <span className="text-slate-300">Auto-sync session capital from Angel One margin</span>
        </label>
      )}

      {isIndexDesk && (
        <label className="flex items-start gap-2 text-sm cursor-pointer rounded-lg border border-slate-800 bg-slate-950/40 p-3">
          <input
            type="checkbox"
            checked={Boolean(config?.expiry_restrictions_enabled ?? true)}
            onChange={(e) => update('expiry_restrictions_enabled', e.target.checked)}
            className="mt-0.5 rounded border-slate-600"
          />
          <span>
            <span className="text-slate-200">Expiry-day restrictions</span>
            <span className="block text-xs text-slate-500 mt-0.5">
              When on, Nifty Thursday / Bank Nifty Wednesday expiry uses a tighter window (11:00–13:00)
              and fewer trades. Turn off to trade expiry like a normal session.
            </span>
          </span>
        </label>
      )}

      <label className="block text-sm">
        <span className="text-slate-400">
          {autoBroker && isIndexDesk ? 'Fallback capital (INR)' : 'Capital Amount (INR)'}
        </span>
        <input
          type="number"
          value={config?.capital ?? 100000}
          onChange={(e) => update('capital', Number(e.target.value))}
          className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2"
        />
        {autoBroker && isIndexDesk && (
          <span className="text-xs text-slate-500 mt-1 block">
            {usingBroker && Number.isFinite(liveSession)
              ? `Live Angel One cash in use: ₹${liveSession.toLocaleString('en-IN')}. Fallback is only used if the broker is disconnected.`
              : 'Used only if Angel One cash cannot be fetched. Save this panel to retry a live sync.'}
          </span>
        )}
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
        <span className="text-slate-400">Max Trades Per Day (0 = unlimited)</span>
        <input
          type="number"
          value={config?.max_trades_per_day ?? 5}
          onChange={(e) => update('max_trades_per_day', Number(e.target.value))}
          className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2"
        />
        <span className="text-xs text-slate-500 mt-1 block">
          Hard limit only. Set to 0 for no daily count cap; AI may still stop earlier after strong wins.
        </span>
      </label>

      <div className="rounded-lg border border-slate-800 p-3 text-sm">
        <p className="text-slate-500 text-xs uppercase">Lot Quantity (auto · full capital)</p>
        <p className="text-2xl font-semibold mt-1">{displayLots} lots</p>
        <p className="text-xs text-slate-500 mt-1">
          Lot size {lotSize} · Option LTP ₹{premium.toFixed(2)}
          {displayLots > 0 && premium > 0 && (
            <> · Deploy ₹{(displayLots * premium * lotSize).toLocaleString('en-IN')}</>
          )}
        </p>
        {positionSizing?.reason && (
          <p className="text-xs text-slate-500 mt-2">{positionSizing.reason}</p>
        )}
        {premium <= 0 && (
          <p className="text-xs text-amber-400/80 mt-2">Connect broker stream for live option premium.</p>
        )}
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
