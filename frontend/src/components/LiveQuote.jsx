import { useState } from 'react'
import { fetchBrokerQuote } from '../api'

export default function LiveQuote() {
  const [symbol, setSymbol] = useState('NSE:RELIANCE')
  const [quote, setQuote] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const handleFetch = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchBrokerQuote(symbol)
      setQuote(data)
    } catch (err) {
      console.error(err)
      setError('Unable to fetch quote')
      setQuote(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-4 bg-white rounded-xl shadow-sm border border-slate-200">
      <h2 className="text-xl font-semibold mb-3">Live Quote</h2>
      <div className="space-y-3">
        <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
          <input
            type="text"
            value={symbol}
            onChange={e => setSymbol(e.target.value)}
            placeholder="Symbol, e.g. NSE:RELIANCE"
            className="w-full rounded border border-slate-300 px-3 py-2 text-slate-900"
          />
          <button
            type="button"
            onClick={handleFetch}
            disabled={loading}
            className="rounded bg-slate-900 px-4 py-2 text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {loading ? 'Fetching…' : 'Fetch'}
          </button>
        </div>
        {error && <div className="text-sm text-red-600">{error}</div>}
        {quote && (
          <div className="space-y-2 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
            <div className="flex justify-between">
              <span>Last Price</span>
              <span>{quote.last_price ?? 'N/A'}</span>
            </div>
            <div className="flex justify-between">
              <span>Bid</span>
              <span>{quote.bid ?? 'N/A'}</span>
            </div>
            <div className="flex justify-between">
              <span>Ask</span>
              <span>{quote.ask ?? 'N/A'}</span>
            </div>
            <div className="flex justify-between">
              <span>Volume</span>
              <span>{quote.volume ?? 'N/A'}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
