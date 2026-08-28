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

function buildCredentialPayload(form, { partial = false } = {}) {
  const payload = {}
  const apiKey = form.api_key.trim()
  const clientCode = form.client_code.trim()
  const password = form.broker_password
  const totp = form.totp_secret.replace(/\s/g, '').toUpperCase()

  if (apiKey) payload.api_key = apiKey
  if (clientCode) payload.client_code = clientCode
  if (password) payload.password = password
  if (totp) payload.totp_secret = totp

  if (!partial) {
    return {
      api_key: apiKey,
      client_code: clientCode,
      password,
      totp_secret: totp,
    }
  }
  return payload
}

export default function BrokerSetupForm({
  onSuccess,
  onCancel,
  showLoginFields = true,
  compact = false,
  credentialsConfigured = false,
  clientCode = null,
}) {
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
      const payload = buildCredentialPayload(form, { partial: credentialsConfigured })
      if (credentialsConfigured && Object.keys(payload).length === 0) {
        setError('Enter at least one field to update, or cancel and use Connect.')
        return
      }
      if (!credentialsConfigured) {
        if (!payload.api_key || !payload.client_code || !payload.password || !payload.totp_secret) {
          setError('API key, client code, broker password, and TOTP secret are all required.')
          return
        }
      }
      await saveBrokerCredentials(payload)
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
      } else if (Array.isArray(detail)) {
        setError(detail.map((d) => d.msg || d).join('; ') || 'Broker setup failed')
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

  const fieldRequired = !credentialsConfigured
  const keepHint = credentialsConfigured ? ' · leave blank to keep saved value' : ''

  return (
    <form onSubmit={handleBrokerSetup} className="space-y-3">
      {credentialsConfigured && (
        <p className="text-xs text-slate-400 bg-slate-950/60 border border-slate-700/60 rounded-lg px-3 py-2">
          Updating saved Angel One credentials
          {clientCode ? ` for ${clientCode}` : ''}. Secrets are never shown — fill only fields you want to change.
        </p>
      )}

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
        API key{keepHint}
        <input
          name="api_key"
          type="password"
          autoComplete="off"
          value={form.api_key}
          onChange={onChange}
          className={inputClass}
          required={fieldRequired}
          minLength={fieldRequired ? 8 : undefined}
          placeholder={credentialsConfigured ? '•••••••• (unchanged)' : ''}
        />
      </label>
      <label className="block text-sm">
        Client code{keepHint}
        <input
          name="client_code"
          value={form.client_code}
          onChange={onChange}
          className={inputClass}
          required={fieldRequired}
          placeholder={credentialsConfigured ? clientCode || 'unchanged' : ''}
        />
      </label>
      <label className="block text-sm">
        Broker password{keepHint}
        <input
          type="password"
          name="broker_password"
          autoComplete="new-password"
          value={form.broker_password}
          onChange={onChange}
          className={inputClass}
          required={fieldRequired}
          placeholder={credentialsConfigured ? '•••••••• (unchanged)' : ''}
        />
      </label>
      <label className="block text-sm">
        TOTP secret (Base32 from authenticator QR — not the 6-digit code){keepHint}
        <input
          name="totp_secret"
          type="password"
          autoComplete="off"
          value={form.totp_secret}
          onChange={onChange}
          className={inputClass}
          required={fieldRequired}
          minLength={fieldRequired ? 16 : undefined}
          placeholder={credentialsConfigured ? '•••••••• (unchanged)' : 'OHW5F5FC...'}
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

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className="flex-1 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold py-2.5 disabled:opacity-50"
        >
          {busy
            ? 'Saving…'
            : credentialsConfigured
              ? 'Update & Connect'
              : 'Save & Connect Broker'}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-lg border border-slate-600 px-4 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
          >
            Cancel
          </button>
        )}
      </div>
    </form>
  )
}
