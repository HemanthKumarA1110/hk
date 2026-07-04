import { useCallback, useState } from 'react'
import { applySMCStrategy, pollSMCBacktest, runSMCBacktest } from '../services/angelOneApi'
import { pollBacktestJob } from './pollBacktestJob'

/** Hook for SMC strategy comparison backtest (async job + polling). */
export function useSMCBacktest(instrument) {
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [applying, setApplying] = useState(false)

  const run = useCallback(
    async (form) => {
      setRunning(true)
      setProgress(5)
      setError('')
      try {
        const data = await pollBacktestJob(
          () => runSMCBacktest(instrument, { ...form, optimize: form.optimize === true }),
          (jobId) => pollSMCBacktest(instrument, jobId),
          setProgress
        )
        setResult(data)
        return data
      } catch (err) {
        const detail = err.response?.data?.detail
        if (typeof detail === 'string') setError(detail)
        else setError(err.message || 'SMC backtest failed')
        return null
      } finally {
        setRunning(false)
      }
    },
    [instrument]
  )

  const applyWinner = useCallback(
    async (report) => {
      setApplying(true)
      setError('')
      try {
        const data = await applySMCStrategy(instrument, report || result)
        return data
      } catch (err) {
        setError(err.response?.data?.detail || err.message || 'Failed to apply SMC strategy')
        return null
      } finally {
        setApplying(false)
      }
    },
    [instrument, result]
  )

  return { running, progress, result, error, applying, run, applyWinner }
}
