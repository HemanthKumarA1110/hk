import { useCallback, useEffect, useState } from 'react'
import { evaluateScalpingDesk, fetchScalpingDesk } from '../services/angelOneApi'

/**
 * Poll scalping desk state from strategy-engine.
 * @param {string} instrument
 * @param {number} [intervalMs=8000]
 */
export function useScalpingStrategy(instrument, intervalMs = 8000) {
  const [desk, setDesk] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      const data = await fetchScalpingDesk(instrument)
      setDesk(data)
      setError('')
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load desk')
    } finally {
      setLoading(false)
    }
  }, [instrument])

  const evaluate = useCallback(async () => {
    setLoading(true)
    try {
      const data = await evaluateScalpingDesk(instrument)
      setDesk(data)
      setError('')
      return data
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Evaluation failed')
      return null
    } finally {
      setLoading(false)
    }
  }, [instrument])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, intervalMs)
    return () => clearInterval(timer)
  }, [refresh, intervalMs])

  return { desk, loading, error, refresh, evaluate }
}
