import { useCallback, useRef, useState } from 'react'
import { fetchBacktestRun, runBacktest } from '../api'

/** Run production-engine backtest for intraday or swing desks. */
export function useDeskBacktest(engine) {
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const pollRef = useRef(null)
  const launchRef = useRef(false)

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const pollRun = useCallback(
    (runId) => {
      stopPoll()
      setProgress(15)
      pollRef.current = setInterval(async () => {
        try {
          const data = await fetchBacktestRun(runId)
          setResult(data)
          if (data.status === 'running') {
            setProgress((p) => Math.min(p + 10, 90))
          }
          if (data.status === 'completed' || data.status === 'failed') {
            setProgress(100)
            stopPoll()
            setRunning(false)
          }
        } catch {
          stopPoll()
          setRunning(false)
          setError('Failed to load backtest result')
        }
      }, 2000)
    },
    [stopPoll]
  )

  const run = useCallback(
    async (form) => {
      if (launchRef.current) return null
      launchRef.current = true
      setRunning(true)
      setProgress(5)
      setError('')
      setResult(null)
      try {
        const payload = {
          engine,
          interval: form.interval,
          from_date: form.from_date,
          to_date: form.to_date,
          initial_capital: form.initial_capital ?? 100000,
          risk_pct: form.risk_pct ?? 1,
          use_demo_data: form.use_demo_data ?? true,
          strategy_code: form.strategy_code || undefined,
          ai_entry: form.ai_entry ?? false,
          ai_exit: form.ai_exit ?? false,
        }
        if (engine === 'intraday' && form.auto_pick_universe !== false) {
          payload.auto_pick_universe = true
          payload.top_n = form.top_n ?? 10
          payload.symbol = 'AUTO-PICK'
        } else if (engine === 'swing' && form.auto_pick_universe !== false) {
          payload.auto_pick_universe = true
          payload.max_open_positions = form.max_open_positions ?? 5
          payload.top_n = form.top_n ?? 15
          payload.symbol = 'AUTO-PICK'
          payload.interval = '1d'
        } else {
          payload.symbol = form.symbol
        }
        const created = await runBacktest(payload)
        if (created.status === 'completed') {
          const data = await fetchBacktestRun(created.run_id)
          setResult(data)
          setProgress(100)
          setRunning(false)
          return data
        }
        setResult({ run_id: created.run_id, status: 'pending' })
        pollRun(created.run_id)
        return created
      } catch (err) {
        const detail = err.response?.data?.detail
        setError(typeof detail === 'string' ? detail : err.message || 'Backtest failed')
        setRunning(false)
        return null
      } finally {
        launchRef.current = false
      }
    },
    [engine, pollRun]
  )

  return { running, progress, result, error, run }
}
