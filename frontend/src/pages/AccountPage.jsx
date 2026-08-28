import { useEffect, useState } from 'react'
import { changePassword, connectBroker, fetchBrokerStatus } from '../api'
import { useAuth } from '../context/AuthContext'
import BrokerReconnectPanel from '../components/BrokerReconnectPanel'
import BrokerSetupForm from '../components/BrokerSetupForm'

export default function AccountPage() {
  const { user } = useAuth()
  const [pwForm, setPwForm] = useState({ current_password: '', new_password: '', confirm: '' })
  const [pwMsg, setPwMsg] = useState('')
  const [pwError, setPwError] = useState('')
  const [pwBusy, setPwBusy] = useState(false)
  const [brokerMsg, setBrokerMsg] = useState('')
  const [brokerStatus, setBrokerStatus] = useState(null)
  const [editingCredentials, setEditingCredentials] = useState(false)

  const loadBrokerStatus = async () => {
    try {
      const status = await fetchBrokerStatus()
      setBrokerStatus(status)
      return status
    } catch {
      setBrokerStatus(null)
      return null
    }
  }

  useEffect(() => {
    loadBrokerStatus()
  }, [])

  const onPwChange = (event) => {
    setPwForm((prev) => ({ ...prev, [event.target.name]: event.target.value }))
  }

  const handleChangePassword = async (event) => {
    event.preventDefault()
    setPwMsg('')
    setPwError('')
    if (pwForm.new_password !== pwForm.confirm) {
      setPwError('New password and confirmation do not match')
      return
    }
    if (pwForm.new_password.length < 8) {
      setPwError('New password must be at least 8 characters')
      return
    }
    setPwBusy(true)
    try {
      await changePassword({
        current_password: pwForm.current_password,
        new_password: pwForm.new_password,
      })
      setPwMsg('Password updated successfully')
      setPwForm({ current_password: '', new_password: '', confirm: '' })
    } catch (err) {
      setPwError(err.response?.data?.detail || 'Failed to change password')
    } finally {
      setPwBusy(false)
    }
  }

  const handleBrokerSaved = async () => {
    setEditingCredentials(false)
    const status = await loadBrokerStatus()
    setBrokerMsg(
      status?.connected
        ? `Broker connected (${status.client_code || 'ok'})`
        : status?.credentials_configured
          ? 'Credentials saved. Use Connect if the session is not active yet.'
          : 'Credentials saved'
    )
  }

  const inputClass = 'mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm'
  const configured = Boolean(brokerStatus?.credentials_configured)
  const connected = Boolean(brokerStatus?.connected)
  const needsReconnect = Boolean(brokerStatus?.needs_reconnect)

  return (
    <div>
      <header className="mb-6">
        <p className="text-emerald-400 text-xs uppercase tracking-widest">Account</p>
        <h2 className="text-3xl font-bold mt-1">Profile & Security</h2>
        <p className="text-slate-400 mt-1">
          {user?.username} · {user?.role} · {user?.email}
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-6">
          <h3 className="font-semibold mb-1">Change password</h3>
          <p className="text-slate-500 text-sm mb-4">Update your platform login password.</p>
          <form onSubmit={handleChangePassword} className="space-y-3">
            <label className="block text-sm text-slate-400">
              Current password
              <input
                type="password"
                name="current_password"
                autoComplete="current-password"
                value={pwForm.current_password}
                onChange={onPwChange}
                className={inputClass}
                required
              />
            </label>
            <label className="block text-sm text-slate-400">
              New password
              <input
                type="password"
                name="new_password"
                autoComplete="new-password"
                value={pwForm.new_password}
                onChange={onPwChange}
                className={inputClass}
                required
                minLength={8}
              />
            </label>
            <label className="block text-sm text-slate-400">
              Confirm new password
              <input
                type="password"
                name="confirm"
                autoComplete="new-password"
                value={pwForm.confirm}
                onChange={onPwChange}
                className={inputClass}
                required
                minLength={8}
              />
            </label>
            {pwError && <p className="text-sm text-rose-400">{pwError}</p>}
            {pwMsg && <p className="text-sm text-emerald-400">{pwMsg}</p>}
            <button
              type="submit"
              disabled={pwBusy}
              className="rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 px-4 py-2 text-sm font-medium"
            >
              {pwBusy ? 'Saving…' : 'Update password'}
            </button>
          </form>
        </section>

        <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-6">
          <h3 className="font-semibold mb-1">Angel One broker</h3>
          <p className="text-slate-500 text-sm mb-4">
            Credentials are stored encrypted and reused until you or an admin changes them.
          </p>
          {brokerMsg && <p className="text-sm text-emerald-400 mb-3">{brokerMsg}</p>}

          {configured && !editingCredentials ? (
            <div className="space-y-3">
              <div className="rounded-lg border border-slate-700 bg-slate-950/50 px-3 py-3 text-sm space-y-1">
                <p>
                  Status:{' '}
                  <span className="text-emerald-400">configured</span>
                  {connected ? ' · connected' : needsReconnect ? ' · reconnect needed' : ' · not connected'}
                </p>
                <p className="text-slate-400">
                  Client code:{' '}
                  <span className="font-mono text-slate-200">{brokerStatus?.client_code || '—'}</span>
                </p>
                <p className="text-slate-500 text-xs">
                  API key / password / TOTP · saved (masked — not displayed)
                </p>
              </div>
              {(!connected || needsReconnect) && (
                <BrokerReconnectPanel
                  mode={!connected ? 'connect' : 'reconnect'}
                  clientCode={brokerStatus?.client_code}
                  onSuccess={async ({ status } = {}) => {
                    if (status) setBrokerStatus(status)
                    else await loadBrokerStatus()
                    setBrokerMsg('Broker session refreshed')
                  }}
                  onChangeCredentials={() => setEditingCredentials(true)}
                />
              )}
              {connected && !needsReconnect && (
                <>
                  <button
                    type="button"
                    className="w-full rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold py-2.5"
                    onClick={async () => {
                      try {
                        await connectBroker()
                        const status = await loadBrokerStatus()
                        setBrokerMsg(
                          status?.connected
                            ? `Reconnected (${status.client_code || 'ok'})`
                            : status?.error || 'Reconnect failed'
                        )
                      } catch (err) {
                        setBrokerMsg(err.response?.data?.detail || 'Reconnect failed')
                      }
                    }}
                  >
                    Refresh broker session
                  </button>
                  <button
                    type="button"
                    className="text-sm text-slate-400 hover:text-slate-200 underline"
                    onClick={() => setEditingCredentials(true)}
                  >
                    Change credentials
                  </button>
                </>
              )}
            </div>
          ) : (
            <BrokerSetupForm
              showLoginFields={false}
              compact
              credentialsConfigured={configured}
              clientCode={brokerStatus?.client_code}
              onCancel={configured ? () => setEditingCredentials(false) : undefined}
              onSuccess={handleBrokerSaved}
            />
          )}
        </section>
      </div>
    </div>
  )
}
