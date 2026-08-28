import { useEffect, useState } from 'react'
import { fetchIndexQuotes } from '../api'

function formatPrice(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }
  return Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

function formatChange(change, changePct) {
  if (change === null || change === undefined || changePct === null || changePct === undefined) {
    return null
  }
  const sign = change >= 0 ? '+' : ''
  return `${sign}${Number(change).toFixed(2)} (${sign}${Number(changePct).toFixed(2)}%)`
}

export default function IndexQuotesPanel({ brokerConnected = false, sessionValid = false }) {
  const [quotes, setQuotes] = useState([])
  const [error, setError] = useState('')
  const liveReady = brokerConnected && sessionValid

  useEffect(() => {
    if (!liveReady) {
      setQuotes([])
      setError('')
      return undefined
    }

    const load = () => {
      fetchIndexQuotes()
        .then((data) => {
          setQuotes(data.indices || [])
          setError('')
        })
        .catch((err) => {
          const detail = err.response?.data?.detail
          setError(typeof detail === 'string' ? detail : 'Unable to load index quotes')
        })
    }

    load()
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [liveReady])

  if (!brokerConnected) {
    return (
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 mb-6">
        <h3 className="font-semibold mb-1">Index Spot</h3>
        <p className="text-sm text-slate-400">Connect Angel One to see live Nifty 50 and Bank Nifty prices.</p>
      </section>
    )
  }

  if (!sessionValid) {
    return (
      <section className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 mb-6">
        <h3 className="font-semibold mb-1 text-amber-200">Index Spot</h3>
        <p className="text-sm text-slate-400">Reconnect broker to refresh Nifty 50 and Bank Nifty quotes.</p>
      </section>
    )
  }

  const byName = Object.fromEntries(quotes.map((quote) => [quote.name, quote]))
  const cards = [
    { key: 'NIFTY', title: 'Nifty 50' },
    { key: 'BANKNIFTY', title: 'Bank Nifty' },
  ]

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 mb-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-emerald-400 text-xs uppercase tracking-widest">Live Spot</p>
          <h3 className="font-semibold">Nifty 50 &amp; Bank Nifty</h3>
        </div>
        <span className="text-xs text-slate-500">Updates every 5s</span>
      </div>

      {error && <p className="text-rose-400 text-sm mb-3">{error}</p>}

      <div className="grid gap-4 md:grid-cols-2">
        {cards.map(({ key, title }) => {
          const quote = byName[key] || {}
          const changeText = formatChange(quote.change, quote.change_pct)
          const tone = (quote.change || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'
          return (
            <div key={key} className="rounded-lg border border-slate-800 bg-slate-950/50 p-4">
              <p className="text-xs uppercase tracking-widest text-slate-500">{title}</p>
              <p className="text-3xl font-bold font-mono mt-2">₹{formatPrice(quote.ltp)}</p>
              {changeText ? <p className={`text-sm mt-2 ${tone}`}>{changeText}</p> : null}
              <div className="grid grid-cols-3 gap-2 mt-3 text-xs text-slate-400">
                <div>
                  <p className="uppercase">Open</p>
                  <p className="font-mono text-slate-200">{formatPrice(quote.open)}</p>
                </div>
                <div>
                  <p className="uppercase">High</p>
                  <p className="font-mono text-slate-200">{formatPrice(quote.high)}</p>
                </div>
                <div>
                  <p className="uppercase">Low</p>
                  <p className="font-mono text-slate-200">{formatPrice(quote.low)}</p>
                </div>
              </div>
              {quote.error && quote.error.toUpperCase() !== 'SUCCESS' ? (
                <p className="text-amber-400 text-xs mt-2">{quote.error}</p>
              ) : null}
            </div>
          )
        })}
      </div>
    </section>
  )
}
