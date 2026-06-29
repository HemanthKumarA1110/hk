import { useState } from 'react'
import { connectBroker, fetchBrokerStatus, fetchMe, login, saveBrokerCredentials } from '../api'

const EMPTY_FORM = {
  username: 'admin',
  password: 'Admin@12345',
  api_key: '',
  client_code: '',
  broker_password: '',
  totp_secret: '',
}

export default function BrokerSetupForm({ onSuccess, showLoginFields = true, compact = false }) {
  const [form, setForm] = useState(EMPTY_FORM)
  const [error, setError] = useState('')
  const [brokerStatus, setBrokerStatus] = useState(null)
  const [busy, setBusy] = useState(false)

  const onChange = (event) => {
    setForm((prev) => ({ ...prev, [event.target.name]: event.target.value }))
  }

  const ensureLoggedIn = async () => {
    if (localStorage.getItem('access_token')) {
      return fetchMe()
    }
    const tokens = await login(form.username, form.password)
    localStorage.setItem('access_token', tokens.access_token)
    localStorage.setItem('refresh_token', tokens.refresh_token)
    return fetchMe()
  }

  const handleBrokerSetup = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    setBrokerStatus(null)
    try {
      const profile = await ensureLoggedIn()
      await saveBrokerCredentials({
        api_key: form.api_key.trim(),
        client_code: form.client_code.trim(),
        password: form.broker_password,
        totp_secret: form.totp_secret.replace(/\s/g, '').toUpperCase(),
      })
      const connectResult = await connectBroker()
      const status = await fetchBrokerStatus()
      const merged = { ...status, ...connectResult }
      setBrokerStatus(merged)

      if (!merged.connected) {
        setError(merged.error || 'Angel One connection failed. Check credentials and TOTP secret.')
        return
      }

      onSuccess?.(profile, merged)
    } catch (err) {
      const detail = err.response?.data?.detail
      if (detail === 'Not authenticated') {
        setError('Session expired. Enter your platform login above and try again.')
      } else {
        setError(typeof detail === 'string' ? detail : 'Broker setup failed')
      }
    } finally {
      setBusy(false)
    }
  }

  const inputClass = compact
    ? 'mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm'
    : 'mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2'

  return (
    <form onSubmit={handleBrokerSetup} className="space-y-3">
      {showLoginFields && !localStorage.getItem('access_token') && (
        <p className="text-xs text-amber-300/90 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
          Platform login is required first. Your admin username/password below will be used to authenticate
          the API before saving Angel One credentials.
        </p>
      )}

      {showLoginFields && !localStorage.getItem('access_token') && (
        <>
          <label className="block text-sm">
            Platform username
            <input
              name="username"
              value={form.username}
              onChange={onChange}
              className={inputClass}
            />
          </label>
          <label className="block text-sm">
            Platform password
            <input
              type="password"
              name="password"
              value={form.password}
              onChange={onChange}
              className={inputClass}
            />
          </label>
        </>
      )}

      <label className="block text-sm">
        API key
        <input name="api_key" value={form.api_key} onChange={onChange} className={inputClass} />
      </label>
      <label className="block text-sm">
        Client code
        <input name="client_code" value={form.client_code} onChange={onChange} className={inputClass} />
      </label>
      <label className="block text-sm">
        Broker password
        <input
          type="password"
          name="broker_password"
          value={form.broker_password}
          onChange={onChange}
          className={inputClass}
        />
      </label>
      <label className="block text-sm">
        TOTP secret (Base32 from authenticator QR — not the 6-digit code)
        <input
          name="totp_secret"
          value={form.totp_secret}
          onChange={onChange}
          className={inputClass}
          placeholder="OHW5F5FC..."
        />
      </label>

      {error && <p className="text-rose-400 text-sm">{error}</p>}
      {brokerStatus?.connected && (
        <p className="text-emerald-400 text-sm">
          Connected as {brokerStatus.client_code}
          {brokerStatus.expires_at ? ` · session until ${new Date(brokerStatus.expires_at).toLocaleString()}` : ''}
        </p>
      )}
      {brokerStatus && !brokerStatus.connected && brokerStatus.error && (
        <p className="text-amber-400 text-sm text-xs">{brokerStatus.error}</p>
      )}

      <button
        type="submit"
        disabled={busy}
        className="w-full rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold py-2.5 disabled:opacity-50"
      >
        {busy ? 'Connecting...' : 'Save & Connect Broker'}
      </button>
    </form>
  )
}
