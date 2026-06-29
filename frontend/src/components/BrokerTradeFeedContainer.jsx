import { useEffect, useState, useCallback } from 'react'
import { fetchOrderTrades } from '../api'
import BrokerTradeFeed from './BrokerTradeFeed'

export default function BrokerTradeFeedContainer({ tradingMode = 'paper' }) {
  const [trades, setTrades] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const isPaper = tradingMode === 'paper'

  const loadTrades = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchOrderTrades()
      setTrades(data.trades || [])
    } catch {
      setError(isPaper ? 'Unable to load paper trades' : 'Connect broker to load live trade feed')
    } finally {
      setLoading(false)
    }
  }, [isPaper])

  useEffect(() => {
    loadTrades()
    const interval = setInterval(loadTrades, 10000)
    return () => clearInterval(interval)
  }, [loadTrades])

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs text-slate-500">
          {isPaper ? 'Paper trade feed · refreshes every 10s' : 'Live broker feed · refreshes every 10s'}
        </p>
        <button
          type="button"
          onClick={loadTrades}
          disabled={loading}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs hover:bg-slate-800"
        >
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>
      {error && <p className="mb-3 text-sm text-amber-400">{error}</p>}
      <BrokerTradeFeed trades={trades} />
    </div>
  )
}
