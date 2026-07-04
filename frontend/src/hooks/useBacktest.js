import { useCallback, useState } from 'react'
import { optimizeScalpingStrategy, pollDeskBacktest, runScalpingBacktest } from '../services/angelOneApi'
import { pollBacktestJob } from './pollBacktestJob'

/** Run scalping desk backtest (async job) and optional AI optimization. */
export function useBacktest(instrument) {
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState(null)
  const [optimization, setOptimization] = useState(null)
  const [error, setError] = useState('')

  const run = useCallback(
    async (form) => {
      setRunning(true)
      setProgress(5)
      setError('')
      try {
        const data = await pollBacktestJob(
          () => runScalpingBacktest(instrument, form),
          (jobId) => pollDeskBacktest(instrument, jobId),
          setProgress
        )
        setResult(data)
        return data
      } catch (err) {
        const detail = err.response?.data?.detail
        if (typeof detail === 'string') setError(detail)
        else setError(err.message || 'Backtest failed')
        return null
      } finally {
        setRunning(false)
      }
    },
    [instrument]
  )

  const optimize = useCallback(
    async (summary) => {
      try {
        const data = await optimizeScalpingStrategy(instrument, summary || result)
        setOptimization(data)
        return data
      } catch (err) {
        setError(err.response?.data?.detail || err.message || 'Optimization failed')
        return null
      }
    },
    [instrument, result]
  )

  return { running, progress, result, optimization, error, run, optimize }
}
