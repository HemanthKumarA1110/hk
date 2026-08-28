import { useCallback, useEffect, useRef, useState } from 'react'
import { ensureMarketStream } from '../services/angelOneApi'

/**
 * Reconnect market stream only if the user already turned Live Market Engine ON.
 * Never force-starts the stream.
 */
export function useEnsureMarketStream({ enabled = true, intervalMs = 60_000 } = {}) {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState('')
  const inFlight = useRef(false)

  const ensure = useCallback(async () => {
    if (!enabled || inFlight.current) return null
    inFlight.current = true
    try {
      const next = await ensureMarketStream()
      setStatus(next)
      setError('')
      return next
    } catch (err) {
      const detail = err?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Unable to refresh market stream')
      return null
    } finally {
      inFlight.current = false
    }
  }, [enabled])

  useEffect(() => {
    if (!enabled) return undefined
    ensure()
    const timer = setInterval(ensure, intervalMs)
    return () => clearInterval(timer)
  }, [enabled, ensure, intervalMs])

  return { status, error, ensure, connected: Boolean(status?.connected) }
}
