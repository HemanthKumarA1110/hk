import { useEffect, useMemo, useState } from 'react'

import EquityCurveChart from './EquityCurveChart'

import MetricCard from './MetricCard'

import SymbolLookupInput from './SymbolLookupInput'

import { defaultStrategyCode, filterStrategiesForDesk } from '../utils/strategyFilters'



const DEFAULT_FROM = new Date(Date.now() - 60 * 86400000).toISOString().slice(0, 10)

const DEFAULT_TO = new Date().toISOString().slice(0, 10)

const SWING_DEFAULT_FROM = new Date(Date.now() - 60 * 86400000).toISOString().slice(0, 10)



/**

 * Collapsible backtest panel for Intraday / Swing desks.

 */

export default function DeskBacktestModule({

  engine,

  accent = 'orange',

  title,

  defaultSymbol = 'SBIN-EQ',

  defaultInterval = '5m',

  strategies = [],

  backtest,

  selectedSymbol,

  defaultOpen = false,

}) {

  const autoPick = engine === 'intraday' || engine === 'swing'

  const [open, setOpen] = useState(defaultOpen)

  const options = useMemo(() => {

    const filtered = filterStrategiesForDesk(engine, strategies)

    if (filtered.length > 0) return filtered

    return [{ code: defaultStrategyCode(engine), label: 'Full Multi-Confirmation', family: engine }]

  }, [engine, strategies])



  const [form, setForm] = useState({

    symbol: defaultSymbol,

    interval: engine === 'swing' ? '1d' : defaultInterval,

    from_date: engine === 'swing' ? SWING_DEFAULT_FROM : DEFAULT_FROM,

    to_date: DEFAULT_TO,

    initial_capital: 100000,

    use_demo_data: false,

    strategy_code: defaultStrategyCode(engine),

    auto_pick_universe: autoPick,

    top_n: 10,

    max_open_positions: 5,

    ai_entry: false,

    ai_exit: false,

  })



  useEffect(() => {

    if (!autoPick && selectedSymbol) {

      setForm((prev) => ({ ...prev, symbol: selectedSymbol }))

    }

  }, [autoPick, selectedSymbol])



  useEffect(() => {

    if (options.length && !options.some((o) => o.code === form.strategy_code)) {

      setForm((prev) => ({ ...prev, strategy_code: options[0].code }))

    }

  }, [options, form.strategy_code])



  const metrics = backtest.result?.metrics

  const pickedStocks = metrics?.picked_stocks || []

  const curvePoints = (backtest.result?.equity_curve || []).map((equity, i) => ({

    date: `#${i + 1}`,

    equity: typeof equity === 'number' ? equity : equity?.equity,

  }))

  const selected = options.find((o) => o.code === form.strategy_code)

  const accentText =

    accent === 'violet' ? 'text-violet-400' : accent === 'cyan' ? 'text-cyan-400' : 'text-orange-400'

  const btnClass =

    accent === 'violet'

      ? 'bg-violet-500 hover:bg-violet-400'

      : accent === 'cyan'

        ? 'bg-cyan-500 hover:bg-cyan-400'

        : 'bg-orange-500 hover:bg-orange-400'

  const barColor = accent === 'violet' ? '#8b5cf6' : accent === 'cyan' ? '#06b6d4' : '#f97316'



  return (

    <section className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden mb-6">

      <button

        type="button"

        onClick={() => setOpen(!open)}

        className="w-full flex items-center justify-between p-4 text-left hover:bg-slate-800/40"

      >

        <div>

          <p className={`${accentText} text-xs uppercase tracking-widest`}>Backtesting</p>

          <h3 className="font-semibold">{title}</h3>

          <p className="text-xs text-slate-500 mt-1">

            {autoPick

              ? 'Auto-picks top Nifty 50 stocks · last 60 days · Angel One 5m data when broker connected'

              : engine === 'swing'

                ? 'SWING-* strategies only · replay on historical OHLCV'

                : 'INTRA-* strategies only · replay on historical OHLCV'}

          </p>

        </div>

        <span className="text-slate-500">{open ? '▼' : '▶'}</span>

      </button>



      {open && (

        <div className="p-4 pt-0 border-t border-slate-800 space-y-4">

          <div className="grid md:grid-cols-2 gap-3">

            <label className="text-sm block md:col-span-2">

              Strategy

              <select

                value={form.strategy_code}

                onChange={(e) => setForm({ ...form, strategy_code: e.target.value })}

                className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-2 py-1.5 text-sm"

              >

                {options.map((s) => (

                  <option key={s.code} value={s.code}>

                    {s.code} — {s.label}

                  </option>

                ))}

              </select>

              {selected?.description && (

                <p className="text-xs text-slate-500 mt-1">{selected.description}</p>

              )}

            </label>



            {autoPick ? (

              <label className="text-sm block md:col-span-2">

                Stock selection

                <div className="mt-1 rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-slate-300">

                  {engine === 'swing'
                    ? 'Top 15 Nifty 50 by 60d backtest preview · ~14mo history loaded for EMA200 warmup · delivery costs'
                    : 'Screens Nifty 50 using volume, range, momentum & strategy fit — no manual symbol needed'}

                </div>

              </label>

            ) : (

              <label className="text-sm block">

                Symbol

                <div className="mt-1">

                  <SymbolLookupInput value={form.symbol} onChange={(symbol) => setForm({ ...form, symbol })} />

                </div>

              </label>

            )}



            {autoPick && engine === 'intraday' && (

              <label className="text-sm">

                Top stocks

                <select

                  value={form.top_n}

                  onChange={(e) => setForm({ ...form, top_n: Number(e.target.value) })}

                  className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-2 py-1.5"

                >

                  {[5, 10, 15, 20].map((n) => (

                    <option key={n} value={n}>

                      Top {n}

                    </option>

                  ))}

                </select>

              </label>

            )}



            {autoPick && engine === 'swing' && (

              <label className="text-sm">

                Max open positions

                <select

                  value={form.max_open_positions}

                  onChange={(e) => setForm({ ...form, max_open_positions: Number(e.target.value) })}

                  className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-2 py-1.5"

                >

                  {[3, 5, 7, 10].map((n) => (

                    <option key={n} value={n}>

                      {n} concurrent

                    </option>

                  ))}

                </select>

              </label>

            )}



            <label className="text-sm">

              From

              <input

                type="date"

                value={form.from_date}

                onChange={(e) => setForm({ ...form, from_date: e.target.value })}

                className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-2 py-1.5"

              />

            </label>

            <label className="text-sm">

              To

              <input

                type="date"

                value={form.to_date}

                onChange={(e) => setForm({ ...form, to_date: e.target.value })}

                className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-2 py-1.5"

              />

            </label>

            <label className="text-sm">

              Interval

              <select

                value={form.interval}

                onChange={(e) => setForm({ ...form, interval: e.target.value })}

                className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-2 py-1.5"

              >

                {(engine === 'swing' ? ['1d'] : ['5m', '15m']).map((i) => (

                  <option key={i} value={i}>

                    {i}

                  </option>

                ))}

              </select>

            </label>

            <label className="text-sm">

              Capital

              <input

                type="number"

                value={form.initial_capital}

                onChange={(e) => setForm({ ...form, initial_capital: Number(e.target.value) })}

                className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-2 py-1.5"

              />

            </label>

          </div>



          <label className="flex items-center gap-2 text-sm text-slate-400">

            <input

              type="checkbox"

              checked={form.use_demo_data}

              onChange={(e) => setForm({ ...form, use_demo_data: e.target.checked })}

            />

            Use demo synthetic data (uncheck for Angel One — broker must be connected)

          </label>



          <div className="flex flex-wrap gap-4 text-sm text-slate-400">

            <label className="flex items-center gap-2">

              <input

                type="checkbox"

                checked={form.ai_entry}

                onChange={(e) => setForm({ ...form, ai_entry: e.target.checked })}

              />

              AI entry filter

            </label>

            <label className="flex items-center gap-2">

              <input

                type="checkbox"

                checked={form.ai_exit}

                onChange={(e) => setForm({ ...form, ai_exit: e.target.checked })}

              />

              AI dynamic exit

            </label>

            <span className="text-xs text-slate-600">

              Compare win rate vs baseline (both off)

            </span>

          </div>



          <button

            type="button"

            disabled={backtest.running}

            onClick={() => backtest.run(form)}

            className={`w-full rounded-lg ${btnClass} text-slate-950 py-2.5 font-semibold disabled:opacity-50`}

          >

            {backtest.running

              ? `Screening & backtesting ${form.strategy_code}…`

              : autoPick

                ? `Run Auto-Pick Backtest · ${form.strategy_code}`

                : `Run Backtest · ${form.strategy_code}`}

          </button>



          {backtest.running && (

            <div className="space-y-1">

              <div className="h-2 rounded-full bg-slate-800">

                <div

                  className="h-full rounded-full transition-all"

                  style={{ width: `${Math.max(backtest.progress || 5, 5)}%`, backgroundColor: barColor }}

                />

              </div>

            </div>

          )}



          {backtest.error && <p className="text-rose-400 text-sm">{backtest.error}</p>}

          {backtest.result?.error_message && (

            <p className="text-rose-400 text-sm">{backtest.result.error_message}</p>

          )}



          {backtest.result?.status === 'completed' && metrics && (

            <>

              <p className="text-sm text-slate-300">

                {form.strategy_code}

                {metrics.universe_screened ? ` · screened ${metrics.universe_screened} stocks` : ''}

                {metrics.symbols_traded ? ` · traded ${metrics.symbols_traded}` : ''}

                {metrics.top_n ? ` · backtested top ${metrics.top_n}` : ''}

                {metrics.max_open_positions ? ` · max ${metrics.max_open_positions} positions` : ''}

                {backtest.result.data_source ? ` · ${backtest.result.data_source}` : ''}

                {metrics.ai_entry ? ' · AI entry' : ''}

                {metrics.ai_exit ? ' · AI exit' : ''}

              </p>

              <div className="grid md:grid-cols-4 gap-3">

                <MetricCard label="Trades" value={metrics.total_trades} />

                <MetricCard label="Win Rate" value={`${metrics.win_rate}%`} />

                <MetricCard label="Total P&L" value={`₹${Number(metrics.total_pnl || 0).toLocaleString('en-IN')}`} />

                <MetricCard label="Profit Factor" value={metrics.profit_factor ?? '—'} />

                <MetricCard label="Max Drawdown" value={`${metrics.max_drawdown}%`} tone="warn" />

                <MetricCard

                  label="Final Capital"

                  value={`₹${Number(metrics.final_capital || 0).toLocaleString('en-IN')}`}

                />

              </div>



              {pickedStocks.length > 0 && (

                <div className="overflow-x-auto">

                  <p className="text-xs text-slate-500 mb-2 uppercase tracking-wider">Auto-picked stocks</p>

                  <table className="w-full text-sm">

                    <thead>

                      <tr className="text-slate-500 border-b border-slate-800">

                        <th className="py-2 text-left">Symbol</th>

                        <th className="py-2 text-right">Score</th>

                        <th className="py-2 text-right">Trades</th>

                        <th className="py-2 text-right">Win %</th>

                        <th className="py-2 text-right">P&L</th>

                      </tr>

                    </thead>

                    <tbody>

                      {pickedStocks.map((row) => (

                        <tr key={row.symbol} className="border-b border-slate-800/60">

                          <td className="py-2 font-mono">{row.symbol}</td>

                          <td className="py-2 text-right">{row.score}</td>

                          <td className="py-2 text-right">{row.total_trades}</td>

                          <td className="py-2 text-right">{row.win_rate}%</td>

                          <td

                            className={`py-2 text-right font-mono ${row.total_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}

                          >

                            ₹{Number(row.total_pnl).toLocaleString('en-IN')}

                          </td>

                        </tr>

                      ))}

                    </tbody>

                  </table>

                </div>

              )}



              {curvePoints.length > 1 && <EquityCurveChart points={curvePoints} />}

              {backtest.result.trades?.length > 0 && (

                <div className="overflow-x-auto">

                  <p className="text-xs text-slate-500 mb-2 uppercase tracking-wider">All trades</p>

                  <table className="w-full text-sm">

                    <thead>

                      <tr className="text-slate-500 border-b border-slate-800">

                        <th className="py-2 text-left">Symbol</th>

                        <th className="py-2 text-left">Side</th>

                        <th className="py-2 text-right">Entry</th>

                        <th className="py-2 text-right">Exit</th>

                        <th className="py-2 text-right">P&L</th>

                      </tr>

                    </thead>

                    <tbody>

                      {backtest.result.trades.slice(0, 20).map((t, idx) => (

                        <tr key={idx} className="border-b border-slate-800/60">

                          <td className="py-2 font-mono text-xs">{t.symbol}</td>

                          <td className="py-2">{t.side}</td>

                          <td className="py-2 text-right font-mono">{t.entry_price}</td>

                          <td className="py-2 text-right font-mono">{t.exit_price}</td>

                          <td

                            className={`py-2 text-right font-mono ${t.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}

                          >

                            ₹{Number(t.pnl).toLocaleString('en-IN')}

                          </td>

                        </tr>

                      ))}

                    </tbody>

                  </table>

                </div>

              )}

            </>

          )}

        </div>

      )}

    </section>

  )

}


