import { useCallback, useEffect, useState } from 'react'
import { fetchStreamStatus } from '../api'

/** Poll Angel One market stream status for live tick age. */
export function useMarketStreamStatus(intervalMs = 3000) {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      const data = await fetchStreamStatus()
      setStatus(data)
      setError('')
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Stream status unavailable')
    }
  }, [])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, intervalMs)
    return () => clearInterval(timer)
  }, [refresh, intervalMs])

  return { status, error, refresh }
}
