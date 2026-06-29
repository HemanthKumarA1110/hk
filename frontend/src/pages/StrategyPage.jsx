import { useState } from 'react'
import StrategySignalsPanel from '../components/StrategySignalsPanel'
import { runStrategies } from '../api'

function formatApiError(err) {
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join('; ')
  return err.message || 'Strategy run failed'
}

export default function StrategyPage() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [refreshToken, setRefreshToken] = useState(0)

  const handleRun = async () => {
    setBusy(true)
    setError('')
    try {
      await runStrategies()
      setRefreshToken((value) => value + 1)
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-emerald-400 text-xs uppercase tracking-widest">Strategy Engine</p>
          <h2 className="text-3xl font-bold mt-1">All Engines</h2>
          <p className="text-slate-400 mt-1">
            Scalping, intraday, and swing signal orchestration with confirmation-based scoring
          </p>
        </div>
        <button
          type="button"
          onClick={handleRun}
          disabled={busy}
          className="rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 px-4 py-2 text-sm font-semibold disabled:opacity-50"
        >
          {busy ? 'Running…' : 'Run All Strategies'}
        </button>
      </header>

      {error && <p className="text-rose-400 text-sm mb-4">{error}</p>}

      <StrategySignalsPanel refreshToken={refreshToken} />
    </div>
  )
}
