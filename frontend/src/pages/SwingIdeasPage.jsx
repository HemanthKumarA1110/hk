import { useCallback, useEffect, useState } from 'react'
import { fetchIndexQuotes, fetchLtp, searchSymbols } from '../api'
import {
  BACKTEST_FRAMEWORK,
  MARKET_CONTEXT,
  RISK_RULES,
  SWING_DESK_META,
  SWING_IDEAS,
} from '../data/swingDeskIdeas'

function formatInr(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

function formatPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null
  const sign = value >= 0 ? '+' : ''
  return `${sign}${Number(value).toFixed(2)}%`
}

function extractLtp(payload) {
  if (!payload || payload.status === false || payload.success === false) return null
  const data = payload.data
  if (!data || typeof data !== 'object') return null
  if (data.ltp != null) return Number(data.ltp)
  for (const value of Object.values(data)) {
    if (value && typeof value === 'object' && value.ltp != null) return Number(value.ltp)
  }
  return null
}

function pickSearchHit(results, tradingsymbol) {
  const list = results?.results || []
  if (!Array.isArray(list) || !list.length) return null
  const want = String(tradingsymbol || '').toUpperCase()
  const exact = list.find((row) => String(row.symbol || '').toUpperCase() === want)
  const base = want.replace(/-EQ$/, '')
  const soft = list.find((row) => String(row.symbol || '').toUpperCase().replace(/-EQ$/, '') === base)
  return exact || soft || list[0]
}

async function resolveAndFetchLtp(idea, tokenCache) {
  const cached = tokenCache[idea.symbol]
  let token = cached?.token
  let tradingsymbol = cached?.tradingsymbol || idea.tradingsymbol

  if (!token) {
    const search = await searchSymbols(idea.symbol.replace(/-EQ$/i, ''), 'NSE', 8)
    const hit = pickSearchHit(search, idea.tradingsymbol)
    if (!hit?.token) {
      throw new Error(`No scrip token for ${idea.symbol}`)
    }
    token = String(hit.token)
    tradingsymbol = hit.symbol || idea.tradingsymbol
    tokenCache[idea.symbol] = { token, tradingsymbol }
  }

  const payload = await fetchLtp('NSE', tradingsymbol, token)
  const ltp = extractLtp(payload)
  if (ltp == null || Number.isNaN(ltp)) {
    throw new Error(payload?.message || `LTP unavailable for ${idea.symbol}`)
  }
  return ltp
}

function ScorePill({ score }) {
  const tone =
    score >= 8.5
      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
      : score >= 7.5
        ? 'bg-sky-500/15 text-sky-300 border-sky-500/30'
        : 'bg-amber-500/15 text-amber-200 border-amber-500/30'
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium ${tone}`}>
      {score.toFixed(1)}/10
    </span>
  )
}

export default function SwingIdeasPage() {
  const [quotes, setQuotes] = useState({})
  const [indices, setIndices] = useState([])
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [lastRefreshed, setLastRefreshed] = useState(null)
  const [tokenCache, setTokenCache] = useState({})
  const [expanded, setExpanded] = useState(() => new Set([1, 2]))

  const refresh = useCallback(async () => {
    setRefreshing(true)
    setError('')
    const nextQuotes = {}
    const nextCache = { ...tokenCache }
    const failures = []

    try {
      const indexData = await fetchIndexQuotes().catch(() => null)
      if (indexData?.indices) setIndices(indexData.indices)

      await Promise.all(
        SWING_IDEAS.map(async (idea) => {
          try {
            const ltp = await resolveAndFetchLtp(idea, nextCache)
            nextQuotes[idea.symbol] = ltp
          } catch (err) {
            failures.push(`${idea.symbol}: ${err.message || 'failed'}`)
          }
        }),
      )

      setTokenCache(nextCache)
      setQuotes((prev) => ({ ...prev, ...nextQuotes }))
      setLastRefreshed(new Date())
      if (failures.length && !Object.keys(nextQuotes).length) {
        setError(
          `Could not refresh live prices. Connect / reconnect Angel One, then try again. (${failures[0]})`,
        )
      } else if (failures.length) {
        setError(`Partial refresh — ${failures.join('; ')}`)
      }
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : err.message || 'Refresh failed')
    } finally {
      setRefreshing(false)
    }
  }, [tokenCache])

  useEffect(() => {
    refresh()
    // Initial load only — manual refresh thereafter
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const toggleExpand = (rank) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(rank)) next.delete(rank)
      else next.add(rank)
      return next
    })
  }

  const byName = Object.fromEntries(indices.map((q) => [q.name, q]))
  const nifty = byName.NIFTY
  const bank = byName.BANKNIFTY

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-violet-400 text-xs uppercase tracking-widest">Research Desk</p>
          <h2 className="text-2xl sm:text-3xl font-bold mt-1">Swing Ideas</h2>
          <p className="text-slate-400 mt-1 text-sm sm:text-base max-w-2xl">
            Top-5 high-conviction Indian swing setups for ~5% in 1–2 months. Thesis seeded{' '}
            {SWING_DESK_META.asOfLabel}; use Refresh for live index and stock quotes.
          </p>
        </div>
        <div className="flex flex-col items-stretch sm:items-end gap-2">
          <button
            type="button"
            onClick={refresh}
            disabled={refreshing}
            className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <svg
              viewBox="0 0 24 24"
              className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`}
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M4 4v6h6M20 20v-6h-6M5 13a7 7 0 0112.2-4.2L20 10M4 14l2.8 1.2A7 7 0 0019 13"
              />
            </svg>
            {refreshing ? 'Refreshing…' : 'Refresh quotes'}
          </button>
          <p className="text-xs text-slate-500">
            {lastRefreshed
              ? `Last refreshed ${lastRefreshed.toLocaleString('en-IN')}`
              : 'Not refreshed yet'}
          </p>
        </div>
      </header>

      {error ? (
        <div className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-100">
          {error}
        </div>
      ) : null}

      <section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-xs text-amber-200">
            {SWING_DESK_META.regime}
          </span>
          <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-xs text-emerald-300">
            Best: {SWING_DESK_META.bestOverall}
          </span>
        </div>
        <p className="text-sm text-slate-300 mb-4">{SWING_DESK_META.objective}</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
            <p className="text-xs text-slate-500">Nifty 50 (live)</p>
            <p className="text-lg font-semibold mt-1">{formatInr(nifty?.ltp)}</p>
            <p
              className={`text-xs mt-0.5 ${
                (nifty?.change_pct || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'
              }`}
            >
              {formatPct(nifty?.change_pct) || '—'}
            </p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
            <p className="text-xs text-slate-500">Bank Nifty (live)</p>
            <p className="text-lg font-semibold mt-1">{formatInr(bank?.ltp)}</p>
            <p
              className={`text-xs mt-0.5 ${
                (bank?.change_pct || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'
              }`}
            >
              {formatPct(bank?.change_pct) || '—'}
            </p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
            <p className="text-xs text-slate-500">Nifty levels</p>
            <p className="text-sm mt-1 text-slate-200">S {MARKET_CONTEXT.niftySupport}</p>
            <p className="text-sm text-slate-400">R {MARKET_CONTEXT.niftyResistance}</p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
            <p className="text-xs text-slate-500">Macro / flows</p>
            <p className="text-sm mt-1 text-slate-300 leading-snug">{MARKET_CONTEXT.vixNote}</p>
          </div>
        </div>
        <p className="text-xs text-slate-500 mt-3">{MARKET_CONTEXT.flows}</p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <span className="text-slate-500">Lead:</span>
          {MARKET_CONTEXT.leaders.map((s) => (
            <span
              key={s}
              className="rounded border border-emerald-500/20 bg-emerald-500/5 px-2 py-0.5 text-emerald-300"
            >
              {s}
            </span>
          ))}
          <span className="text-slate-500 ml-2">Avoid:</span>
          {MARKET_CONTEXT.avoid.map((s) => (
            <span
              key={s}
              className="rounded border border-rose-500/20 bg-rose-500/5 px-2 py-0.5 text-rose-300"
            >
              {s}
            </span>
          ))}
        </div>
      </section>

      <section className="mb-6 overflow-x-auto rounded-xl border border-slate-800">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-900/80 text-slate-400 text-left">
            <tr>
              <th className="px-3 py-3 font-medium">#</th>
              <th className="px-3 py-3 font-medium">Stock</th>
              <th className="px-3 py-3 font-medium">Live / Seed</th>
              <th className="px-3 py-3 font-medium">Score</th>
              <th className="px-3 py-3 font-medium">Buy zone</th>
              <th className="px-3 py-3 font-medium">SL</th>
              <th className="px-3 py-3 font-medium">T1 / T2</th>
              <th className="px-3 py-3 font-medium">R:R</th>
            </tr>
          </thead>
          <tbody>
            {SWING_IDEAS.map((idea) => {
              const live = quotes[idea.symbol]
              return (
                <tr key={idea.symbol} className="border-t border-slate-800 hover:bg-slate-900/40">
                  <td className="px-3 py-3 text-violet-300 font-medium">{idea.rank}</td>
                  <td className="px-3 py-3">
                    <div className="font-medium text-slate-100">{idea.symbol}</div>
                    <div className="text-xs text-slate-500">{idea.sector}</div>
                  </td>
                  <td className="px-3 py-3">
                    <div className="font-medium">{formatInr(live ?? idea.seedCmp)}</div>
                    <div className="text-xs text-slate-500">
                      {live != null ? 'live' : `seed ${formatInr(idea.seedCmp)}`}
                    </div>
                  </td>
                  <td className="px-3 py-3">
                    <ScorePill score={idea.score} />
                  </td>
                  <td className="px-3 py-3 text-slate-300 whitespace-nowrap">{idea.buyZone}</td>
                  <td className="px-3 py-3 text-rose-300">{formatInr(idea.sl)}</td>
                  <td className="px-3 py-3 text-emerald-300 whitespace-nowrap">
                    {formatInr(idea.t1)} / {formatInr(idea.t2)}
                  </td>
                  <td className="px-3 py-3 text-slate-300">{idea.rr}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>

      <div className="space-y-3 mb-8">
        {SWING_IDEAS.map((idea) => {
          const open = expanded.has(idea.rank)
          const live = quotes[idea.symbol]
          return (
            <article
              key={idea.symbol}
              className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden"
            >
              <button
                type="button"
                onClick={() => toggleExpand(idea.rank)}
                className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-slate-900"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-violet-300 text-sm font-semibold">#{idea.rank}</span>
                    <span className="font-semibold">
                      {idea.symbol} — {idea.name}
                    </span>
                    <ScorePill score={idea.score} />
                    <span className="text-xs text-slate-500">{idea.confidence}</span>
                  </div>
                  <p className="text-sm text-slate-400 mt-1 truncate">{idea.why}</p>
                </div>
                <span className="text-slate-500 shrink-0">{open ? '−' : '+'}</span>
              </button>
              {open ? (
                <div className="border-t border-slate-800 px-4 py-4 space-y-4">
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-sm">
                    <div>
                      <p className="text-xs text-slate-500">CMP</p>
                      <p className="font-medium mt-0.5">{formatInr(live ?? idea.seedCmp)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500">Ideal buy / SL</p>
                      <p className="mt-0.5 text-slate-200">{idea.buyZone}</p>
                      <p className="text-rose-300">SL {formatInr(idea.sl)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500">Targets / hold</p>
                      <p className="mt-0.5 text-emerald-300">
                        T1 {formatInr(idea.t1)} · T2 {formatInr(idea.t2)}
                      </p>
                      <p className="text-slate-400">
                        {idea.hold} · {idea.rr}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500">Entry range</p>
                      <p className="mt-0.5 text-slate-200">{idea.entry}</p>
                    </div>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2 text-sm">
                    <p>
                      <span className="text-slate-500">Technical: </span>
                      <span className="text-slate-300">{idea.technical}</span>
                    </p>
                    <p>
                      <span className="text-slate-500">Fundamental: </span>
                      <span className="text-slate-300">{idea.fundamental}</span>
                    </p>
                    <p>
                      <span className="text-slate-500">News / events: </span>
                      <span className="text-slate-300">{idea.news}</span>
                    </p>
                    <p>
                      <span className="text-slate-500">Institutional: </span>
                      <span className="text-slate-300">{idea.institutional}</span>
                    </p>
                    <p>
                      <span className="text-slate-500">Key risks: </span>
                      <span className="text-rose-200/90">{idea.risks}</span>
                    </p>
                    <p>
                      <span className="text-slate-500">Watch: </span>
                      <span className="text-slate-300">{idea.events}</span>
                    </p>
                  </div>
                </div>
              ) : null}
            </article>
          )
        })}
      </div>

      <section className="mb-6 grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h3 className="font-semibold mb-3">Setup backtest framework</h3>
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs sm:text-sm">
              <thead className="text-slate-500 text-left">
                <tr>
                  <th className="pb-2 pr-3 font-medium">Setup</th>
                  <th className="pb-2 pr-3 font-medium">Win</th>
                  <th className="pb-2 pr-3 font-medium">Hold</th>
                  <th className="pb-2 font-medium">Winner</th>
                </tr>
              </thead>
              <tbody>
                {BACKTEST_FRAMEWORK.map((row) => (
                  <tr key={row.setup} className="border-t border-slate-800">
                    <td className="py-2 pr-3 text-slate-300">{row.setup}</td>
                    <td className="py-2 pr-3 text-emerald-300">{row.winRate}</td>
                    <td className="py-2 pr-3 text-slate-400">{row.avgHold}</td>
                    <td className="py-2 text-slate-300">{row.winner}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-slate-500 mt-3">
            Historical characteristics of these setup types — not a guarantee for any single name.
          </p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h3 className="font-semibold mb-3">Risk management</h3>
          <p className="text-xs uppercase tracking-wide text-slate-500 mb-2">Position sizing</p>
          <ul className="space-y-1.5 text-sm text-slate-300 mb-4">
            {RISK_RULES.sizing.map((item) => (
              <li key={item} className="flex gap-2">
                <span className="text-emerald-400 shrink-0">•</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
          <p className="text-xs uppercase tracking-wide text-slate-500 mb-2">Do not enter</p>
          <ul className="space-y-1.5 text-sm text-slate-300">
            {RISK_RULES.skip.map((item) => (
              <li key={item} className="flex gap-2">
                <span className="text-rose-400 shrink-0">•</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="rounded-xl border border-violet-500/20 bg-violet-500/5 p-4">
        <h3 className="font-semibold text-violet-200 mb-2">Desk summary</h3>
        <p className="text-sm text-slate-300 leading-relaxed mb-2">
          Correction odds (1–2 months): {SWING_DESK_META.correctionOdds}
        </p>
        <p className="text-sm text-slate-300 leading-relaxed">{SWING_DESK_META.strategy}</p>
        <p className="text-xs text-slate-500 mt-3">
          Research brief for discretionary use — not SEBI-registered advice. Reconfirm live quotes,
          circuit limits, and corporate actions before entry.
        </p>
      </section>
    </div>
  )
}
