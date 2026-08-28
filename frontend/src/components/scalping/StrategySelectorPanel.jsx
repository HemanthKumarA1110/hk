const REGIME_LABELS = {
  TRENDING_UP: 'Trending Up',
  TRENDING_DOWN: 'Trending Down',
  RANGING: 'Ranging',
  HIGH_VOLATILITY: 'High Volatility',
  LOW_VOLATILITY: 'Low Volatility',
  TRENDING_BULL: 'Trending Bull',
  TRENDING_BEAR: 'Trending Bear',
  RANGE_BOUND: 'Range Bound',
  EVENT_DRIVEN: 'Event Driven',
}

const FAMILY_LABELS = {
  battle: 'Battle-Tested',
  adaptive: 'Adaptive',
  smc: 'SMC',
}

/**
 * Strategy catalog — list all strategies with unique codes and enable toggles.
 */
export default function StrategySelectorPanel({
  selection,
  availableStrategies = [],
  strategyFamilies = [],
  config,
  onChange,
  marketRegime,
  mtfContext,
  orbConfirmation,
  expiryHandler,
  eodReview,
  weeklyTuning,
  onWeeklyTune,
  lastPattern,
  lastLossAutopsy,
  lastWinReinforcement,
}) {
  if (!selection && !config) return null

  const ctx = selection?.market_context || {}
  const rankings = selection?.rankings || []
  const scalpRegime = marketRegime?.regime || ctx.scalp_regime
  const regime = scalpRegime || selection?.regime || ctx.regime
  const regimeSummary = marketRegime?.summary || ctx.regime_summary
  const regimeAdj = marketRegime?.adjustments || ctx.regime_adjustments
  const mtf = mtfContext || selection?.mtf_context || ctx.mtf || {}
  const orb = orbConfirmation || selection?.orb_confirmation || {}
  const expiry = expiryHandler || selection?.expiry_handler || {}
  const eod = eodReview || selection?.eod_review || {}
  const tune = weeklyTuning || selection?.weekly_tuning || {}
  const pattern = lastPattern || selection?.last_pattern || {}
  const autopsy = lastLossAutopsy || selection?.last_loss_autopsy || {}
  const win = lastWinReinforcement || selection?.last_win_reinforcement || {}
  const mode = config?.strategy_mode || 'auto'
  const strategies = availableStrategies.length > 0 ? availableStrategies : []
  const settings = config?.strategy_settings || {}
  const isManual = mode === 'manual'

  const update = (patch) => onChange?.({ ...config, ...patch })

  const updateStrategy = (code, patch) => {
    const next = { ...(config?.strategy_settings || {}) }
    next[code] = { ...(next[code] || {}), ...patch }
    update({ strategy_settings: next })
  }

  const setAllEnabled = (enabled) => {
    const next = { ...(config?.strategy_settings || {}) }
    strategies.forEach((s) => {
      next[s.code] = { ...(next[s.code] || { execution_mode: 'live' }), enabled }
    })
    update({ strategy_settings: next })
  }

  const enabledStrategies = strategies.filter((s) => {
    const sCfg = settings[s.code] || s
    return sCfg.enabled ?? s.enabled
  })
  const monitorCount = isManual ? enabledStrategies.length : strategies.length

  return (
    <section className="rounded-xl border border-violet-500/20 bg-violet-500/5 p-4 space-y-3">
      <div>
        <p className="text-violet-400 text-xs uppercase tracking-widest">Strategy Catalog</p>
        <h3 className="font-semibold text-lg">All Scalping Strategies</h3>
        <p className="text-xs text-slate-500 mt-1">
          With AI Auto Trading ON, monitored strategies are scanned every ~1s. The first valid signal places
          the order; the desk manages SL, target, trailing stop, and exit. No new trade until the current one
          is fully closed.
        </p>
      </div>

      <div className="flex gap-2">
        {[
          ['auto', 'Auto (all strategies)'],
          ['manual', 'Manual (selected)'],
        ].map(([m, label]) => (
          <button
            key={m}
            type="button"
            onClick={() => update({ strategy_mode: m })}
            className={`flex-1 rounded-lg py-2 text-xs font-medium ${
              mode === m ? 'bg-violet-500 text-white' : 'border border-slate-700 text-slate-400'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <p className="text-slate-400">
          Monitoring <span className="text-slate-200 font-medium">{monitorCount}</span> strateg
          {monitorCount === 1 ? 'y' : 'ies'}
          {isManual ? ' (your selection)' : ' (full catalog)'}
        </p>
        {isManual && strategies.length > 0 && (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setAllEnabled(true)}
              className="rounded border border-slate-700 px-2 py-1 text-slate-300 hover:bg-slate-800"
            >
              Select all
            </button>
            <button
              type="button"
              onClick={() => setAllEnabled(false)}
              className="rounded border border-slate-700 px-2 py-1 text-slate-300 hover:bg-slate-800"
            >
              Clear
            </button>
          </div>
        )}
      </div>

      {!isManual && (
        <p className="text-[11px] text-violet-300/80 bg-violet-500/10 border border-violet-500/20 rounded-lg px-3 py-2">
          Auto mode monitors every strategy below. Switch to Manual to activate only the ones you check.
        </p>
      )}
      {isManual && enabledStrategies.length === 0 && (
        <p className="text-[11px] text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
          Select at least one strategy to monitor in Manual mode.
        </p>
      )}

      <div className="rounded-xl border border-slate-800 overflow-x-auto">
        <table className="w-full text-xs min-w-[640px]">
          <thead className="bg-slate-950/60 text-slate-500 uppercase">
            <tr>
              <th className="text-left p-2">Code</th>
              <th className="text-left p-2">Strategy</th>
              <th className="text-left p-2">Family</th>
              <th className="text-center p-2">{isManual ? 'Active' : 'Default'}</th>
              <th className="text-center p-2">Exec</th>
            </tr>
          </thead>
          <tbody>
            {strategies.length === 0 && (
              <tr>
                <td colSpan={5} className="p-4 text-center text-slate-500">
                  Loading strategies…
                </td>
              </tr>
            )}
            {strategies.map((s) => {
              const sCfg = settings[s.code] || { enabled: s.enabled, execution_mode: 'live' }
              const active = selection?.selected_strategy_code === s.code
              const monitoring = !isManual || Boolean(sCfg.enabled)
              return (
                <tr
                  key={s.code}
                  className={`border-t border-slate-800 ${active ? 'bg-violet-500/10' : ''} ${
                    !monitoring ? 'opacity-50' : ''
                  }`}
                >
                  <td className="p-2 font-mono text-amber-300 whitespace-nowrap">{s.code}</td>
                  <td className="p-2">
                    <p className="font-medium text-slate-200">{s.label}</p>
                    <p className="text-slate-500 mt-0.5 leading-snug">{s.description}</p>
                  </td>
                  <td className="p-2 text-slate-400">{FAMILY_LABELS[s.family] || s.family}</td>
                  <td className="p-2 text-center">
                    {isManual ? (
                      <input
                        type="checkbox"
                        checked={Boolean(sCfg.enabled)}
                        onChange={(e) => updateStrategy(s.code, { enabled: e.target.checked })}
                        className="rounded border-slate-600"
                      />
                    ) : (
                      <span className="text-emerald-400/80">On</span>
                    )}
                  </td>
                  <td className="p-2 text-center">
                    <span className="text-emerald-400/80">Live</span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-slate-500">
        Enabled strategies place live Angel One orders when the master AI Auto Trading toggle is ON.
      </p>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-2">
          <p className="text-slate-500">Regime</p>
          <p className="font-medium text-violet-300 mt-0.5">{REGIME_LABELS[regime] || regime || '—'}</p>
          {regimeSummary && <p className="text-slate-500 mt-1 leading-snug">{regimeSummary}</p>}
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-2">
          <p className="text-slate-500">Volume</p>
          <p className="font-medium mt-0.5">{ctx.volume_ratio != null ? `${ctx.volume_ratio}× avg` : '—'}</p>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-2">
          <p className="text-slate-500">Direction</p>
          <p className="font-medium mt-0.5 capitalize">{ctx.direction || '—'}</p>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-2">
          <p className="text-slate-500">PCR</p>
          <p className="font-medium mt-0.5">{ctx.pcr ?? '—'}</p>
        </div>
      </div>

      {regimeAdj && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-2 text-xs text-slate-400">
          SL ×{regimeAdj.sl_multiplier ?? 1} · size ×{regimeAdj.size_multiplier ?? 1} ·{' '}
          {regimeAdj.allowed_directions ?? 'both'}
        </div>
      )}

      {mtf?.trend_1h && (
        <div className="rounded-lg border border-sky-500/20 bg-sky-500/5 p-3 text-xs space-y-1">
          <p className="text-sky-400 font-medium">Multi-timeframe</p>
          <p className="text-slate-300">
            1h {mtf.trend_1h} · 15m {mtf.alignment_15m} · bias {mtf.bias_score > 0 ? '+' : ''}
            {mtf.bias_score ?? 0}
          </p>
        </div>
      )}

      {orb?.or_high != null && (
        <div className="rounded-lg border border-orange-500/20 bg-orange-500/5 p-3 text-xs space-y-1">
          <p className="text-orange-400 font-medium">Opening range</p>
          <p className="text-slate-300">
            H {orb.or_high} · L {orb.or_low} · {orb.or_range} pts
          </p>
        </div>
      )}

      {(expiry?.is_expiry || expiry?.is_special_session) && (
        <div className="rounded-lg border border-rose-500/25 bg-rose-500/10 p-3 text-xs space-y-2">
          <p className="text-rose-400 font-medium">Expiry day</p>
          <p className="text-slate-300">{expiry.warning}</p>
          <label className="flex items-start gap-2 cursor-pointer text-slate-300">
            <input
              type="checkbox"
              checked={Boolean(config?.expiry_restrictions_enabled ?? true)}
              onChange={(e) => update({ expiry_restrictions_enabled: e.target.checked })}
              className="mt-0.5 rounded border-slate-600"
            />
            <span>
              Apply expiry-day restrictions
              <span className="block text-slate-500 mt-0.5">
                Off = trade this session like a normal day (full windows, normal max trades).
              </span>
            </span>
          </label>
        </div>
      )}

      {eod?.top_lesson && (
        <div className="rounded-lg border border-indigo-500/25 bg-indigo-500/10 p-3 text-xs space-y-1">
          <p className="text-indigo-400 font-medium">EOD self-review</p>
          <p className="text-slate-300">{eod.top_lesson}</p>
        </div>
      )}

      <div className="rounded-lg border border-cyan-500/25 bg-cyan-500/10 p-3 text-xs space-y-2">
        <p className="text-cyan-400 font-medium">Weekly parameter tuner</p>
        {tune?.reasoning ? (
          <p className="text-slate-300">{tune.reasoning}</p>
        ) : (
          <p className="text-slate-500">Analyse last 5 sessions and suggest parameter tweaks.</p>
        )}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => onWeeklyTune?.(false)}
            className="flex-1 rounded-lg border border-slate-700 py-1.5 text-slate-300 hover:bg-slate-800"
          >
            Analyse week
          </button>
          <button
            type="button"
            onClick={() => onWeeklyTune?.(true)}
            disabled={!tune?.mode || tune.mode === 'hold'}
            className="flex-1 rounded-lg bg-cyan-600 py-1.5 text-white disabled:opacity-40"
          >
            Apply tune
          </button>
        </div>
      </div>

      {pattern?.setup_fingerprint && (
        <div className="rounded-lg border border-amber-500/25 bg-amber-500/10 p-3 text-xs">
          <p className="text-amber-400 font-medium">Pattern memory</p>
          <p className="text-slate-300 mt-1">{pattern.setup_fingerprint}</p>
        </div>
      )}

      {autopsy?.root_cause && (
        <div className="rounded-lg border border-rose-500/25 bg-rose-500/10 p-3 text-xs">
          <p className="text-rose-400 font-medium">Loss autopsy · {autopsy.root_label || autopsy.root_cause}</p>
          <p className="text-slate-300 mt-1">{autopsy.description}</p>
        </div>
      )}

      {win?.trade_grade && (
        <div className="rounded-lg border border-emerald-500/25 bg-emerald-500/10 p-3 text-xs">
          <p className="text-emerald-400 font-medium">Win reinforcement · grade {win.trade_grade}</p>
          <p className="text-slate-300 mt-1">{win.key_success_factor}</p>
        </div>
      )}

      {selection?.selected_label && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm">
          <p className="text-emerald-400 font-medium">
            Active: {selection.selected_strategy_code ? `${selection.selected_strategy_code} · ` : ''}
            {selection.selected_label}
          </p>
          <p className="text-xs text-slate-400 mt-1">{selection.selection_reason}</p>
          {selection.selected_score > 0 && (
            <p className="text-xs text-slate-500 mt-1">Fit score {selection.selected_score}%</p>
          )}
        </div>
      )}

      {rankings.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 mb-2">Adaptive rankings (live)</p>
          <ul className="space-y-1">
            {rankings.map((r) => (
              <li
                key={r.strategy_id}
                className={`flex justify-between text-xs rounded px-2 py-1 ${
                  r.strategy_id === selection?.selected_strategy ? 'bg-violet-500/20 text-violet-200' : 'text-slate-400'
                }`}
              >
                <span>{r.label}</span>
                <span>{r.score}%</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
