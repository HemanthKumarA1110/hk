import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchOrderStatus } from '../../api'
import { useAngelOneWebSocket } from '../../hooks/useAngelOneWebSocket'
import { useScalpingStrategy } from '../../hooks/useScalpingStrategy'
import { useAIDecision } from '../../hooks/useAIDecision'
import { useBacktest } from '../../hooks/useBacktest'
import { useSMCBacktest } from '../../hooks/useSMCBacktest'
import { saveScalpingDeskConfig, toggleScalpingAutoTrading, runWeeklyParameterTune } from '../../services/angelOneApi'
import { INSTRUMENT_META } from '../../types/scalping.types'
import LiveChart from './LiveChart'
import TradeConfigPanel from './TradeConfigPanel'
import AIAutoToggle from './AIAutoToggle'
import SignalCard from './SignalCard'
import ActiveTradeCard from './ActiveTradeCard'
import DailyPnLBar from './DailyPnLBar'
import SMCDashboardBar from './SMCDashboardBar'
import BacktestModule from './BacktestModule'
import SMCBacktestPanel from './SMCBacktestPanel'
import AIOptimizationPanel from './AIOptimizationPanel'
import StrategySelectorPanel from './StrategySelectorPanel'
import StreamStatusPanel from './StreamStatusPanel'
import TradingModeToggle from '../TradingModeToggle'
import { filterStrategiesForDesk } from '../../utils/strategyFilters'

/**
 * Shared scalping desk page for NIFTY / BANKNIFTY.
 * @param {{ instrument: 'nifty50' | 'banknifty' }} props
 */
export default function ScalpingDeskPage({ instrument }) {
  const meta = INSTRUMENT_META[instrument]
  const { desk, loading, error, refresh, evaluate } = useScalpingStrategy(instrument, 12000)
  const lastWsRefresh = useRef(0)
  const debouncedRefresh = useCallback(() => {
    const now = Date.now()
    if (now - lastWsRefresh.current < 15000) return
    lastWsRefresh.current = now
    refresh()
  }, [refresh])
  useAngelOneWebSocket(debouncedRefresh)
  const ai = useAIDecision(desk)
  const backtest = useBacktest(instrument)
  const smcBacktest = useSMCBacktest(instrument)

  const [config, setConfig] = useState(null)
  const [toast, setToast] = useState('')
  const [optimization, setOptimization] = useState(null)
  const [orderStatus, setOrderStatus] = useState(null)

  useEffect(() => {
    fetchOrderStatus().then(setOrderStatus).catch(() => null)
  }, [])

  useEffect(() => {
    if (desk?.config) setConfig(desk.config)
  }, [desk?.config])

  const scalpingStrategies = useMemo(
    () => filterStrategiesForDesk('scalping', desk?.available_strategies || []),
    [desk?.available_strategies]
  )

  const showToast = useCallback((msg) => {
    setToast(msg)
    setTimeout(() => setToast(''), 4000)
  }, [])

  const handleTradingModeChange = useCallback(
    (status) => {
      setOrderStatus(status)
      showToast(status?.trading_mode === 'live' ? 'Live trading mode enabled' : 'Paper trading mode active')
      refresh()
    },
    [refresh, showToast]
  )

  const isPaper = (orderStatus?.trading_mode || desk?.trading_mode || 'paper') === 'paper'

  useEffect(() => {
    if (desk?.signal?.status === 'approved') showToast(`Signal: ${desk.signal.signal_type} · AI ${desk.signal.ai?.confidence}%`)
  }, [desk?.signal?.timestamp, showToast])

  const persistConfig = useCallback(
    async (next) => {
      setConfig(next)
      try {
        await saveScalpingDeskConfig(instrument, next)
        showToast('Configuration saved')
        refresh()
      } catch {
        showToast('Failed to save config')
      }
    },
    [instrument, refresh, showToast]
  )

  const handleAutoToggle = async (enabled) => {
    try {
      await toggleScalpingAutoTrading(instrument, enabled)
      showToast(enabled ? 'AI Auto Trading enabled' : 'AI Auto Trading disabled')
      refresh()
    } catch {
      showToast('Failed to toggle auto trading')
    }
  }

  const handleBacktest = async (form) => {
    const data = await backtest.run({
      ...form,
      capital: cfg.capital,
      max_loss_per_day: cfg.max_loss_per_day,
      capital_utilization_pct: cfg.capital_utilization_pct ?? 0.95,
    })
    if (data?.total_trades != null) {
      showToast(`Backtest complete: ${data.total_trades} trades`)
      backtest.optimize(data).then((opt) => {
        if (opt) setOptimization(opt)
      })
    }
  }

  const handleWeeklyTune = async (apply = false) => {
    try {
      const tuning = await runWeeklyParameterTune(instrument, { apply, days: 5 })
      showToast(
        apply
          ? `Weekly tune applied (${tuning.mode}) — vol ${tuning.vol_ratio}`
          : `Weekly tune: ${tuning.mode} · ${tuning.confidence} confidence`
      )
      refresh()
    } catch {
      showToast('Weekly parameter tune failed')
    }
  }

  const strikes = desk?.strikes || {}
  const atmCe = strikes.atm_ce
  const atmPe = strikes.atm_pe
  const cfg = config || desk?.config || {}
  const optionLtp = atmCe?.ltp || atmPe?.ltp || 0

  return (
    <div className="space-y-6">
      {toast && (
        <div className="fixed top-4 right-4 z-50 rounded-lg bg-slate-800 border border-slate-600 px-4 py-2 text-sm shadow-lg">
          {toast}
        </div>
      )}

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-amber-400 text-xs uppercase tracking-widest">Scalping Desk</p>
          <h2 className="text-3xl font-bold mt-1">{meta.label}</h2>
          <p className="text-slate-400 mt-1">
            9 strategies · buy CE/PE only · per-strategy paper or live auto-trading
          </p>
          {orderStatus && (
            <p className="text-xs mt-2 text-slate-500">
              Desk orders use {isPaper ? 'paper (live Angel One quotes, dummy orders in app)' : 'live'} execution
              {!isPaper ? ' · turn on AI Auto Trading for live entries' : ''}
            </p>
          )}
          <p className="text-xs text-slate-500 mt-2">
            Spot ₹{Number(desk?.spot || 0).toLocaleString('en-IN')} ({desk?.spot_change_pct ?? 0}%)
            · {desk?.strategy_label || 'AI Adaptive Scalp'} v{desk?.strategy_version || 4}
            {desk?.strategy_selection?.regime && ` · ${desk.strategy_selection.regime}`}
          </p>
        </div>
        <button
          type="button"
          onClick={evaluate}
          disabled={loading}
          className="rounded-lg bg-amber-500 hover:bg-amber-400 text-slate-950 font-semibold px-5 py-2.5 disabled:opacity-50"
        >
          {loading ? 'Evaluating…' : 'Run Strategy'}
        </button>
      </header>

      {error && <p className="text-rose-400 text-sm">{error}</p>}

      <TradingModeToggle onChange={handleTradingModeChange} />

      <StreamStatusPanel deskStatus={desk?.stream_status} onStreamStarted={refresh} />

      <DailyPnLBar summary={desk?.daily_summary} guards={desk?.guards} dailyStop={desk?.daily_stop} />
      <SMCDashboardBar stats={desk?.smc_dashboard} />

      <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
        <div className="space-y-6">
          <LiveChart candles={desk?.candles || []} timeframe={cfg.timeframe || '1m'} />

          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h3 className="font-semibold mb-3">Option Strikes · Spot {Number(desk?.spot || 0).toFixed(0)}</h3>
            <div className="grid md:grid-cols-3 gap-3 text-sm">
              <StrikeBox title="ATM CE" data={atmCe} />
              <StrikeBox title="ATM PE" data={atmPe} />
              <StrikeBox title="ITM CE" data={strikes.itm_ce} />
              <StrikeBox title="OTM CE" data={strikes.otm_ce} />
              <StrikeBox title="ITM PE" data={strikes.itm_pe} />
              <StrikeBox title="OTM PE" data={strikes.otm_pe} />
            </div>
          </section>

          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h3 className="font-semibold mb-3">Live Signals</h3>
            <div className="space-y-2 max-h-80 overflow-auto">
              {(desk?.signals || []).length === 0 && !ai.latest && (
                <p className="text-sm text-slate-500">No signals — waiting for setup confirmation…</p>
              )}
              {ai.latest && <SignalCard signal={ai.latest} />}
              {(desk?.signals || []).slice(1).map((s, i) => (
                <SignalCard key={`${s.timestamp}-${i}`} signal={s} />
              ))}
            </div>
          </section>

          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h3 className="font-semibold mb-3">Active Trades</h3>
            <div className="space-y-2">
              {(desk?.active_trades || []).length === 0 && (
                <p className="text-sm text-slate-500">No open positions</p>
              )}
              {(desk?.active_trades || []).map((t, i) => (
                <ActiveTradeCard key={t.order_id || i} trade={t} />
              ))}
            </div>
          </section>

          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 overflow-x-auto">
            <h3 className="font-semibold mb-3">Today&apos;s History</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-500 border-b border-slate-800">
                  <th className="py-2 text-left">Type</th>
                  <th className="py-2">Entry</th>
                  <th className="py-2">Exit</th>
                  <th className="py-2">P&L</th>
                  <th className="py-2">AI</th>
                </tr>
              </thead>
              <tbody>
                {(desk?.trade_history || []).map((t, i) => (
                  <tr key={i} className="border-b border-slate-800/60">
                    <td className="py-2">{t.signal_type}</td>
                    <td className="py-2 text-center font-mono">₹{t.entry}</td>
                    <td className="py-2 text-center font-mono">₹{t.exit ?? '—'}</td>
                    <td className={`py-2 text-center font-mono ${(t.pnl || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      ₹{t.pnl ?? '—'}
                    </td>
                    <td className="py-2 text-center">{t.ai?.confidence ?? '—'}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>

        <div className="space-y-4">
          <AIAutoToggle
            enabled={Boolean(cfg.auto_trading_enabled)}
            onToggle={handleAutoToggle}
            isPaper={isPaper}
          />
          <StrategySelectorPanel
            selection={desk?.strategy_selection}
            availableStrategies={scalpingStrategies}
            strategyFamilies={desk?.strategy_families}
            marketRegime={desk?.market_regime}
            mtfContext={desk?.mtf_context}
            orbConfirmation={desk?.orb_confirmation}
            expiryHandler={desk?.expiry_handler}
            eodReview={desk?.eod_review}
            weeklyTuning={desk?.weekly_tuning}
            onWeeklyTune={handleWeeklyTune}
            lastPattern={desk?.last_pattern}
            lastLossAutopsy={desk?.last_loss_autopsy}
            lastWinReinforcement={desk?.last_win_reinforcement}
            config={cfg}
            onChange={persistConfig}
            globalPaperMode={isPaper}
          />
          <TradeConfigPanel
            instrument={instrument}
            config={cfg}
            onChange={persistConfig}
            optionLtp={optionLtp}
            computedLots={desk?.computed_lots}
            capitalInfo={desk?.capital_info}
            positionSizing={desk?.position_sizing}
          />
        </div>
      </div>

      <BacktestModule
        instrument={instrument}
        backtest={backtest}
        onRun={handleBacktest}
        strategies={scalpingStrategies}
        deskCapital={cfg.capital}
        capitalUtilizationPct={cfg.capital_utilization_pct ?? 0.95}
      />
      <SMCBacktestPanel
        instrument={instrument}
        smcBacktest={smcBacktest}
        onApply={() => {
          showToast('Winning SMC strategy applied — paper mode active')
          refresh()
        }}
      />
      <AIOptimizationPanel
        optimization={optimization || backtest.optimization}
        strategyVersion={desk?.strategy_version || 1}
        onApply={() => {
          showToast('Strategy parameters updated from AI suggestions')
          refresh()
        }}
      />
    </div>
  )
}

function StrikeBox({ title, data }) {
  if (!data) return <div className="rounded-lg border border-slate-800 p-3 text-slate-500">{title}: —</div>
  return (
    <div className="rounded-lg border border-slate-800 p-3">
      <p className="text-xs text-slate-500">{title} · {data.strike}</p>
      <p className="font-mono font-semibold">₹{Number(data.ltp).toFixed(2)}</p>
      <p className={`text-xs ${data.change_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
        {data.change_pct}% · Vol {data.volume ?? 0} · OI {data.oi ?? 0}
      </p>
    </div>
  )
}
