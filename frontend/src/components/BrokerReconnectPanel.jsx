import { useState } from 'react'
import { connectBroker, fetchBrokerFunds, fetchBrokerStatus } from '../api'

export default function BrokerReconnectPanel({
  onSuccess,
  onChangeCredentials,
  mode = 'reconnect',
  clientCode = null,
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const isConnect = mode === 'connect'
  const title = isConnect ? 'Angel One Configured' : 'Session Expired'
  const body = isConnect
    ? 'Credentials are saved encrypted. Connect to start a live Angel One session — no need to re-enter API key, password, or TOTP.'
    : 'Angel One credentials are saved, but the live session token is invalid. Reconnect to refresh margin, market data, and order routing.'
  const buttonLabel = busy
    ? isConnect
      ? 'Connecting…'
      : 'Reconnecting…'
    : isConnect
      ? 'Connect Angel One'
      : 'Reconnect Angel One'

  const handleReconnect = async () => {
    setBusy(true)
    setError('')
    try {
      const result = await connectBroker()
      if (!result.connected) {
        setError(result.error || 'Connect failed. Update credentials if Angel One details changed.')
        return
      }
      const [status, funds] = await Promise.all([
        fetchBrokerStatus(),
        fetchBrokerFunds().catch(() => null),
      ])
      onSuccess?.({ status, funds })
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Connect failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      className={`rounded-xl border p-4 ${
        isConnect
          ? 'border-emerald-500/30 bg-emerald-500/5'
          : 'border-amber-500/30 bg-amber-500/5'
      }`}
    >
      <h3 className={`font-semibold mb-1 ${isConnect ? 'text-emerald-200' : 'text-amber-200'}`}>
        {title}
      </h3>
      {clientCode && (
        <p className="text-xs text-slate-400 mb-2">
          Client code: <span className="text-slate-200 font-mono">{clientCode}</span>
        </p>
      )}
      <p className="text-sm text-slate-400 mb-4">{body}</p>
      {error && <p className="text-rose-400 text-sm mb-3">{error}</p>}
      <button
        type="button"
        onClick={handleReconnect}
        disabled={busy}
        className="w-full rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold py-2.5 disabled:opacity-50"
      >
        {buttonLabel}
      </button>
      {onChangeCredentials && (
        <button
          type="button"
          onClick={onChangeCredentials}
          className="mt-3 w-full text-sm text-slate-400 hover:text-slate-200 underline"
        >
          Change credentials
        </button>
      )}
    </section>
  )
}
