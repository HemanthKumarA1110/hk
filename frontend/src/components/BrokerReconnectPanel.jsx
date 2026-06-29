import { useState } from 'react'
import { connectBroker, fetchBrokerFunds, fetchBrokerStatus } from '../api'

export default function BrokerReconnectPanel({ onSuccess }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const handleReconnect = async () => {
    setBusy(true)
    setError('')
    try {
      const result = await connectBroker()
      if (!result.connected) {
        setError(result.error || 'Reconnect failed. Check Angel One credentials and TOTP secret.')
        return
      }
      const [status, funds] = await Promise.all([
        fetchBrokerStatus(),
        fetchBrokerFunds().catch(() => null),
      ])
      onSuccess?.({ status, funds })
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Reconnect failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
      <h3 className="font-semibold mb-1 text-amber-200">Session Expired</h3>
      <p className="text-sm text-slate-400 mb-4">
        Angel One credentials are saved, but the live session token is invalid. Reconnect to
        refresh margin, market data, and order routing.
      </p>
      {error && <p className="text-rose-400 text-sm mb-3">{error}</p>}
      <button
        type="button"
        onClick={handleReconnect}
        disabled={busy}
        className="w-full rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold py-2.5 disabled:opacity-50"
      >
        {busy ? 'Reconnecting…' : 'Reconnect Angel One'}
      </button>
    </section>
  )
}
