import { useCallback, useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import {
  connectUserBroker,
  createUser,
  fetchUserBrokerStatus,
  listUsers,
  resetUserPassword,
  saveUserBrokerCredentials,
  updateUser,
} from '../api'
import { useAuth } from '../context/AuthContext'
import {
  ALL_PAGE_KEYS,
  DEFAULT_TRADER_PAGES,
  PAGE_CATALOG,
  defaultPagesForRole,
} from '../config/pages'

const EMPTY_CREATE = {
  username: '',
  email: '',
  password: '',
  role: 'trader',
  is_active: true,
  allowed_pages: [...DEFAULT_TRADER_PAGES],
}

function PageAccessChecklist({ value, onChange, disabled, lockAdmin }) {
  const pages = lockAdmin
    ? PAGE_CATALOG
    : PAGE_CATALOG.filter((p) => p.key !== 'admin_users')

  const toggle = (key) => {
    if (disabled || lockAdmin) return
    if (key === 'account') return
    const next = value.includes(key) ? value.filter((k) => k !== key) : [...value, key]
    if (!next.includes('account')) next.push('account')
    onChange(next)
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 max-h-56 overflow-y-auto rounded-lg border border-slate-800 bg-slate-950/40 p-2">
      {pages.map((page) => {
        const checked = lockAdmin || value.includes(page.key)
        const locked = lockAdmin || page.key === 'account'
        return (
          <label
            key={page.key}
            className={`flex min-h-[40px] items-center gap-2 rounded px-2 py-2 text-xs ${
              locked ? 'text-slate-500' : 'text-slate-300 cursor-pointer hover:bg-slate-900'
            }`}
          >
            <input
              type="checkbox"
              className="rounded border-slate-600"
              checked={checked}
              disabled={disabled || locked}
              onChange={() => toggle(page.key)}
            />
            <span>{page.label}</span>
          </label>
        )
      })}
    </div>
  )
}

const EMPTY_BROKER = {
  api_key: '',
  client_code: '',
  password: '',
  totp_secret: '',
}

export default function UsersAdminPage() {
  const { user } = useAuth()
  const [users, setUsers] = useState([])
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [createForm, setCreateForm] = useState(EMPTY_CREATE)
  const [selectedId, setSelectedId] = useState(null)
  const [resetPassword, setResetPassword] = useState('')
  const [brokerForm, setBrokerForm] = useState(EMPTY_BROKER)
  const [brokerStatus, setBrokerStatus] = useState(null)
  const [editingBroker, setEditingBroker] = useState(false)
  const [pageDraft, setPageDraft] = useState([])

  const loadUsers = useCallback(async () => {
    try {
      const rows = await listUsers()
      setUsers(rows)
      setError('')
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load users')
    }
  }, [])

  useEffect(() => {
    if (user?.role === 'admin') loadUsers()
  }, [user, loadUsers])

  if (user?.role !== 'admin') {
    return <Navigate to="/" replace />
  }

  const selected = users.find((u) => u.id === selectedId) || null

  const flash = (text, isError = false) => {
    if (isError) {
      setError(text)
      setMsg('')
    } else {
      setMsg(text)
      setError('')
    }
  }

  const handleCreate = async (event) => {
    event.preventDefault()
    setBusy(true)
    try {
      await createUser(createForm)
      setCreateForm(EMPTY_CREATE)
      flash(`Created user ${createForm.username}`)
      await loadUsers()
    } catch (err) {
      flash(err.response?.data?.detail || 'Create failed', true)
    } finally {
      setBusy(false)
    }
  }

  const handleToggleActive = async (row) => {
    setBusy(true)
    try {
      await updateUser(row.id, { is_active: !row.is_active })
      flash(`${row.username} ${row.is_active ? 'deactivated' : 'activated'}`)
      await loadUsers()
    } catch (err) {
      flash(err.response?.data?.detail || 'Update failed', true)
    } finally {
      setBusy(false)
    }
  }

  const handleRoleChange = async (row, role) => {
    setBusy(true)
    try {
      const updated = await updateUser(row.id, { role })
      flash(`Role for ${row.username} set to ${role}`)
      await loadUsers()
      if (selectedId === row.id) {
        setPageDraft(
          role === 'admin' ? [...ALL_PAGE_KEYS] : [...(updated.allowed_pages || defaultPagesForRole(role))]
        )
      }
    } catch (err) {
      flash(err.response?.data?.detail || 'Role update failed', true)
    } finally {
      setBusy(false)
    }
  }

  const handleResetPassword = async (event) => {
    event.preventDefault()
    if (!selected) return
    setBusy(true)
    try {
      await resetUserPassword(selected.id, resetPassword)
      setResetPassword('')
      flash(`Password reset for ${selected.username}`)
    } catch (err) {
      flash(err.response?.data?.detail || 'Password reset failed', true)
    } finally {
      setBusy(false)
    }
  }

  const selectUser = async (row) => {
    setSelectedId(row.id)
    setBrokerForm(EMPTY_BROKER)
    setBrokerStatus(null)
    setEditingBroker(false)
    setPageDraft(
      row.role === 'admin'
        ? [...ALL_PAGE_KEYS]
        : [...(row.allowed_pages || defaultPagesForRole(row.role))]
    )
    try {
      const status = await fetchUserBrokerStatus(row.id)
      setBrokerStatus(status)
      setEditingBroker(!status?.credentials_configured)
    } catch {
      setBrokerStatus(null)
      setEditingBroker(true)
    }
  }

  const handleSavePages = async () => {
    if (!selected) return
    setBusy(true)
    try {
      const updated = await updateUser(selected.id, { allowed_pages: pageDraft })
      setPageDraft([...(updated.allowed_pages || pageDraft)])
      flash(`Page access updated for ${selected.username}`)
      await loadUsers()
    } catch (err) {
      flash(err.response?.data?.detail || 'Page access update failed', true)
    } finally {
      setBusy(false)
    }
  }

  const handleConnectBroker = async () => {
    if (!selected) return
    setBusy(true)
    try {
      const connectResult = await connectUserBroker(selected.id)
      setBrokerStatus(connectResult)
      flash(
        connectResult.connected
          ? `Angel One connected for ${selected.username}`
          : connectResult.error || `Connect incomplete for ${selected.username}`,
        !connectResult.connected
      )
    } catch (err) {
      flash(err.response?.data?.detail || 'Broker connect failed', true)
    } finally {
      setBusy(false)
    }
  }

  const handleSaveBroker = async (event) => {
    event.preventDefault()
    if (!selected) return
    setBusy(true)
    try {
      const configured = Boolean(brokerStatus?.credentials_configured)
      const payload = {}
      const apiKey = brokerForm.api_key.trim()
      const clientCode = brokerForm.client_code.trim()
      const password = brokerForm.password
      const totp = brokerForm.totp_secret.replace(/\s/g, '').toUpperCase()
      if (apiKey) payload.api_key = apiKey
      if (clientCode) payload.client_code = clientCode
      if (password) payload.password = password
      if (totp) payload.totp_secret = totp

      if (!configured) {
        if (!apiKey || !clientCode || !password || !totp) {
          flash('API key, client code, password, and TOTP secret are all required for first-time setup', true)
          return
        }
      } else if (Object.keys(payload).length === 0) {
        flash('Enter at least one field to update, or use Connect with saved credentials', true)
        return
      }

      await saveUserBrokerCredentials(selected.id, payload)
      const connectResult = await connectUserBroker(selected.id)
      setBrokerStatus(connectResult)
      setEditingBroker(false)
      flash(
        connectResult.connected
          ? `Angel One connected for ${selected.username}`
          : connectResult.error || `Credentials saved for ${selected.username}; connect incomplete`
      )
      setBrokerForm(EMPTY_BROKER)
    } catch (err) {
      const detail = err.response?.data?.detail
      flash(typeof detail === 'string' ? detail : 'Broker save failed', true)
    } finally {
      setBusy(false)
    }
  }

  const inputClass = 'mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm'

  return (
    <div>
      <header className="mb-6">
        <p className="text-amber-400 text-xs uppercase tracking-widest">Admin</p>
        <h2 className="text-2xl sm:text-3xl font-bold mt-1">Users & API Access</h2>
        <p className="text-slate-400 mt-1 text-sm sm:text-base">
          Create users, control which pages they can open, reset passwords, and configure Angel One credentials.
        </p>
      </header>

      {(error || msg) && (
        <div
          className={`mb-4 rounded-lg border px-3 py-2 text-sm ${
            error
              ? 'border-rose-500/30 bg-rose-500/10 text-rose-300'
              : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
          }`}
        >
          {error || msg}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-3">
        <section className="xl:col-span-2 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h3 className="font-semibold mb-3">Users</h3>
          <div className="overflow-x-auto -mx-1 px-1">
            <table className="w-full text-sm min-w-[640px]">
              <thead className="text-xs uppercase text-slate-500">
                <tr>
                  <th className="text-left p-2">ID</th>
                  <th className="text-left p-2">Username</th>
                  <th className="text-left p-2">Email</th>
                  <th className="text-left p-2">Role</th>
                  <th className="text-left p-2">Active</th>
                  <th className="text-right p-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((row) => (
                  <tr
                    key={row.id}
                    className={`border-t border-slate-800 ${
                      selectedId === row.id ? 'bg-emerald-500/5' : ''
                    }`}
                  >
                    <td className="p-2 text-slate-500">{row.id}</td>
                    <td className="p-2 font-medium">{row.username}</td>
                    <td className="p-2 text-slate-400">{row.email}</td>
                    <td className="p-2">
                      <select
                        value={row.role}
                        disabled={busy}
                        onChange={(e) => handleRoleChange(row, e.target.value)}
                        className="min-h-[36px] rounded bg-slate-950 border border-slate-700 px-2 py-1.5 text-xs"
                      >
                        <option value="admin">admin</option>
                        <option value="trader">trader</option>
                        <option value="viewer">viewer</option>
                      </select>
                    </td>
                    <td className="p-2">
                      <span
                        className={`inline-flex rounded-md px-2 py-0.5 text-xs font-medium ${
                          row.is_active
                            ? 'bg-emerald-500/15 text-emerald-400'
                            : 'bg-slate-700/60 text-slate-400'
                        }`}
                      >
                        {row.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="p-2 text-right whitespace-nowrap">
                      <div className="inline-flex flex-wrap justify-end gap-2">
                        <button
                          type="button"
                          className="min-h-[36px] rounded-md border border-emerald-500/30 px-2.5 py-1.5 text-xs text-emerald-400 hover:bg-emerald-500/10"
                          onClick={() => selectUser(row)}
                        >
                          Configure
                        </button>
                        <button
                          type="button"
                          className={`min-h-[36px] rounded-md border px-2.5 py-1.5 text-xs font-medium disabled:opacity-40 ${
                            row.is_active
                              ? 'border-rose-500/30 text-rose-400 hover:bg-rose-500/10'
                              : 'border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10'
                          }`}
                          disabled={busy || row.id === user.id}
                          title={
                            row.id === user.id
                              ? 'You cannot deactivate your own account'
                              : row.is_active
                                ? 'Block this user from logging in'
                                : 'Allow this user to log in again'
                          }
                          onClick={() => handleToggleActive(row)}
                        >
                          {row.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h3 className="font-semibold mb-3">Create user</h3>
          <form onSubmit={handleCreate} className="space-y-3">
            <label className="block text-sm text-slate-400">
              Username
              <input
                className={inputClass}
                value={createForm.username}
                required
                minLength={3}
                onChange={(e) => setCreateForm((p) => ({ ...p, username: e.target.value }))}
              />
            </label>
            <label className="block text-sm text-slate-400">
              Email
              <input
                type="email"
                className={inputClass}
                value={createForm.email}
                required
                onChange={(e) => setCreateForm((p) => ({ ...p, email: e.target.value }))}
              />
            </label>
            <label className="block text-sm text-slate-400">
              Temporary password
              <input
                type="password"
                className={inputClass}
                value={createForm.password}
                required
                minLength={8}
                onChange={(e) => setCreateForm((p) => ({ ...p, password: e.target.value }))}
              />
            </label>
            <label className="block text-sm text-slate-400">
              Role
              <select
                className={inputClass}
                value={createForm.role}
                onChange={(e) => {
                  const role = e.target.value
                  setCreateForm((p) => ({
                    ...p,
                    role,
                    allowed_pages: defaultPagesForRole(role),
                  }))
                }}
              >
                <option value="trader">trader</option>
                <option value="viewer">viewer</option>
                <option value="admin">admin</option>
              </select>
            </label>
            <div className="block text-sm text-slate-400">
              <div className="flex items-center justify-between gap-2 mb-1">
                <span>Allowed pages</span>
                {createForm.role !== 'admin' && (
                  <button
                    type="button"
                    className="text-xs text-emerald-400 hover:underline"
                    onClick={() =>
                      setCreateForm((p) => ({
                        ...p,
                        allowed_pages: defaultPagesForRole(p.role),
                      }))
                    }
                  >
                    Reset defaults
                  </button>
                )}
              </div>
              <PageAccessChecklist
                value={createForm.allowed_pages}
                disabled={busy}
                lockAdmin={createForm.role === 'admin'}
                onChange={(allowed_pages) => setCreateForm((p) => ({ ...p, allowed_pages }))}
              />
              {createForm.role === 'admin' && (
                <p className="text-xs text-slate-500 mt-1">Admins always get every page, including Users Admin.</p>
              )}
            </div>
            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 px-4 py-2 text-sm font-medium"
            >
              Create user
            </button>
          </form>
        </section>
      </div>

      {selected && (
        <div className="grid gap-6 lg:grid-cols-2 mt-6">
          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 lg:col-span-2">
            <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
              <div>
                <h3 className="font-semibold mb-1">Page access · {selected.username}</h3>
                <p className="text-slate-500 text-sm">
                  Checked pages appear in the sidebar and can be opened directly.
                </p>
              </div>
              {selected.role !== 'admin' && (
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="text-xs text-slate-400 hover:underline"
                    onClick={() => setPageDraft(defaultPagesForRole(selected.role))}
                  >
                    Defaults
                  </button>
                  <button
                    type="button"
                    className="text-xs text-slate-400 hover:underline"
                    onClick={() =>
                      setPageDraft(
                        PAGE_CATALOG.filter((p) => p.key !== 'admin_users').map((p) => p.key)
                      )
                    }
                  >
                    Select all
                  </button>
                </div>
              )}
            </div>
            <PageAccessChecklist
              value={pageDraft}
              disabled={busy}
              lockAdmin={selected.role === 'admin'}
              onChange={setPageDraft}
            />
            {selected.role === 'admin' ? (
              <p className="text-xs text-slate-500 mt-2">Admins always retain full page access.</p>
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={handleSavePages}
                className="mt-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 px-4 py-2 text-sm font-medium"
              >
                Save page access
              </button>
            )}
          </section>

          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h3 className="font-semibold mb-1">Reset password · {selected.username}</h3>
            <p className="text-slate-500 text-sm mb-3">Admin override — user can change it later on Account.</p>
            <form onSubmit={handleResetPassword} className="space-y-3">
              <label className="block text-sm text-slate-400">
                New password
                <input
                  type="password"
                  className={inputClass}
                  value={resetPassword}
                  required
                  minLength={8}
                  onChange={(e) => setResetPassword(e.target.value)}
                />
              </label>
              <button
                type="submit"
                disabled={busy}
                className="rounded-lg border border-slate-600 px-4 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
              >
                Reset password
              </button>
            </form>
          </section>

          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h3 className="font-semibold mb-1">Angel One API · {selected.username}</h3>
            <p className="text-slate-500 text-sm mb-3">
              Credentials are encrypted with ENCRYPTION_KEY and stored per user_id. Connect reuses saved
              secrets — only enter fields when creating or changing them.
              {brokerStatus && (
                <span className="block mt-1 text-xs text-slate-400">
                  Status: {brokerStatus.credentials_configured ? 'configured' : 'not set'}
                  {brokerStatus.connected ? ' · connected' : ''}
                  {brokerStatus.needs_reconnect ? ' · reconnect needed' : ''}
                  {brokerStatus.client_code ? ` · ${brokerStatus.client_code}` : ''}
                </span>
              )}
            </p>

            {brokerStatus?.credentials_configured && !editingBroker ? (
              <div className="space-y-3">
                <div className="rounded-lg border border-slate-700 bg-slate-950/50 px-3 py-3 text-sm space-y-1">
                  <p className="text-emerald-400">Configured (secrets masked)</p>
                  <p className="text-slate-400">
                    Client code:{' '}
                    <span className="font-mono text-slate-200">{brokerStatus.client_code || '—'}</span>
                  </p>
                  <p className="text-slate-500 text-xs">API key / password / TOTP · saved</p>
                </div>
                <button
                  type="button"
                  disabled={busy}
                  onClick={handleConnectBroker}
                  className="w-full rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold py-2.5 disabled:opacity-50"
                >
                  {busy ? 'Connecting…' : brokerStatus.connected ? 'Reconnect / refresh session' : 'Connect with saved credentials'}
                </button>
                <button
                  type="button"
                  className="text-sm text-slate-400 hover:text-slate-200 underline"
                  onClick={() => {
                    setBrokerForm(EMPTY_BROKER)
                    setEditingBroker(true)
                  }}
                >
                  Change credentials
                </button>
              </div>
            ) : (
              <form onSubmit={handleSaveBroker} className="space-y-3">
                {brokerStatus?.credentials_configured && (
                  <p className="text-xs text-slate-400">
                    Leave fields blank to keep the saved value. Fill only what you want to change.
                  </p>
                )}
                <label className="block text-sm text-slate-400">
                  API key
                  <input
                    type="password"
                    autoComplete="off"
                    className={inputClass}
                    value={brokerForm.api_key}
                    required={!brokerStatus?.credentials_configured}
                    minLength={brokerStatus?.credentials_configured ? undefined : 8}
                    placeholder={brokerStatus?.credentials_configured ? '•••••••• (unchanged)' : ''}
                    onChange={(e) => setBrokerForm((p) => ({ ...p, api_key: e.target.value }))}
                  />
                </label>
                <label className="block text-sm text-slate-400">
                  Client code
                  <input
                    className={inputClass}
                    value={brokerForm.client_code}
                    required={!brokerStatus?.credentials_configured}
                    placeholder={
                      brokerStatus?.credentials_configured
                        ? brokerStatus.client_code || 'unchanged'
                        : ''
                    }
                    onChange={(e) => setBrokerForm((p) => ({ ...p, client_code: e.target.value }))}
                  />
                </label>
                <label className="block text-sm text-slate-400">
                  Broker password
                  <input
                    type="password"
                    autoComplete="new-password"
                    className={inputClass}
                    value={brokerForm.password}
                    required={!brokerStatus?.credentials_configured}
                    placeholder={brokerStatus?.credentials_configured ? '•••••••• (unchanged)' : ''}
                    onChange={(e) => setBrokerForm((p) => ({ ...p, password: e.target.value }))}
                  />
                </label>
                <label className="block text-sm text-slate-400">
                  TOTP secret
                  <input
                    type="password"
                    autoComplete="off"
                    className={inputClass}
                    value={brokerForm.totp_secret}
                    required={!brokerStatus?.credentials_configured}
                    minLength={brokerStatus?.credentials_configured ? undefined : 16}
                    placeholder={brokerStatus?.credentials_configured ? '•••••••• (unchanged)' : ''}
                    onChange={(e) => setBrokerForm((p) => ({ ...p, totp_secret: e.target.value }))}
                  />
                </label>
                <div className="flex gap-2">
                  <button
                    type="submit"
                    disabled={busy}
                    className="rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 px-4 py-2 text-sm font-medium"
                  >
                    {brokerStatus?.credentials_configured ? 'Update & connect' : 'Save & connect'}
                  </button>
                  {brokerStatus?.credentials_configured && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setBrokerForm(EMPTY_BROKER)
                        setEditingBroker(false)
                      }}
                      className="rounded-lg border border-slate-600 px-4 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </form>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
