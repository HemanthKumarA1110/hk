import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchLtp } from '../api'
import SymbolLookupInput from '../components/SymbolLookupInput'
import { useAuth } from '../context/AuthContext'

const STORAGE_PREFIX = 'stock-monitor:'
const POLL_MS = 10_000
const ALERT_SOUND_MS = 180

function storageKey(userId) {
  return `${STORAGE_PREFIX}${userId ?? 'guest'}`
}

function formatInr(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

function extractLtp(payload) {
  if (!payload || payload.status === false || payload.success === false) return null
  const data = payload.data
  if (!data || typeof data !== 'object') return null
  if (data.ltp != null) return Number(data.ltp)
  for (const value of Object.values(data)) {
    if (value && typeof value === 'object' && value.ltp != null) return Number(value.ltp)
  }
  return null
}

function numOrNull(value) {
  if (value === '' || value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function loadWatchlist(userId) {
  try {
    const raw = localStorage.getItem(storageKey(userId))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed?.items) ? parsed.items : []
  } catch {
    return []
  }
}

function saveWatchlist(userId, items) {
  localStorage.setItem(
    storageKey(userId),
    JSON.stringify({ items, savedAt: new Date().toISOString() }),
  )
}

/**
 * Heuristic long-side verdict using optional buy-zone + SL/target geometry.
 * Not a strategy signal — a monitor helper while the tab is open.
 */
export function evaluateBuyVerdict({ ltp, buyBelow, stoploss, target }) {
  if (ltp == null || Number.isNaN(ltp)) {
    return { label: 'WAITING', tone: 'slate', detail: 'Waiting for live price' }
  }

  const sl = numOrNull(stoploss)
  const tgt = numOrNull(target)
  const zone = numOrNull(buyBelow)

  if (sl != null && ltp <= sl) {
    return { label: 'AVOID', tone: 'rose', detail: 'At or below stoploss' }
  }
  if (tgt != null && ltp >= tgt) {
    return { label: 'TARGET HIT', tone: 'amber', detail: 'Price already at/above target' }
  }
  if (zone != null && ltp <= zone) {
    return { label: 'GOOD TO BUY', tone: 'emerald', detail: `At or below buy zone ${formatInr(zone)}` }
  }
  if (sl != null && tgt != null && ltp > sl && ltp < tgt) {
    const risk = ltp - sl
    const reward = tgt - ltp
    if (risk > 0) {
      const rr = reward / risk
      if (rr >= 2) {
        return { label: 'GOOD TO BUY', tone: 'emerald', detail: `Reward/risk ${rr.toFixed(1)}× looks open` }
      }
      if (rr >= 1.2) {
        return { label: 'WATCH', tone: 'sky', detail: `Reward/risk ${rr.toFixed(1)}× — wait for better entry` }
      }
      return { label: 'AVOID', tone: 'rose', detail: `Reward/risk only ${rr.toFixed(1)}×` }
    }
  }
  if (zone != null && ltp > zone) {
    const stretch = ((ltp - zone) / zone) * 100
    if (stretch <= 0.8) {
      return { label: 'WATCH', tone: 'sky', detail: `${stretch.toFixed(2)}% above buy zone` }
    }
    return { label: 'WAIT', tone: 'amber', detail: `${stretch.toFixed(1)}% above buy zone` }
  }

  return {
    label: 'SET LEVELS',
    tone: 'slate',
    detail: 'Add buy zone and/or SL + target for a verdict',
  }
}

function checkLevelAlerts(item, ltp) {
  if (ltp == null) return []
  const fired = []
  const sl = numOrNull(item.stoploss)
  const tgt = numOrNull(item.target)
  const alerts = item.alertsFired || {}

  if (sl != null && ltp <= sl && !alerts.stoploss) {
    fired.push({
      kind: 'stoploss',
      message: `${item.display} hit stoploss ${formatInr(sl)} (LTP ${formatInr(ltp)})`,
    })
  }
  if (tgt != null && ltp >= tgt && !alerts.target) {
    fired.push({
      kind: 'target',
      message: `${item.display} hit target ${formatInr(tgt)} (LTP ${formatInr(ltp)})`,
    })
  }
  return fired
}

function toneClass(tone) {
  const map = {
    emerald: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
    sky: 'border-sky-500/40 bg-sky-500/10 text-sky-300',
    amber: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
    rose: 'border-rose-500/40 bg-rose-500/10 text-rose-300',
    slate: 'border-slate-600 bg-slate-800/60 text-slate-300',
  }
  return map[tone] || map.slate
}

function beep() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext
    if (!Ctx) return
    const ctx = new Ctx()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.type = 'sine'
    osc.frequency.value = 880
    gain.gain.value = 0.04
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.start()
    setTimeout(() => {
      osc.stop()
      ctx.close()
    }, ALERT_SOUND_MS)
  } catch {
    /* ignore */
  }
}

function notifyBrowser(title, body) {
  if (typeof Notification === 'undefined') return
  if (Notification.permission === 'granted') {
    try {
      new Notification(title, { body })
    } catch {
      /* ignore */
    }
  }
}

export default function StockMonitorPage() {
  const { user } = useAuth()
  const [items, setItems] = useState(() => loadWatchlist(user?.id))
  const [pending, setPending] = useState(null)
  const [quotes, setQuotes] = useState({})
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [lastRefreshed, setLastRefreshed] = useState(null)
  const [toastAlerts, setToastAlerts] = useState([])
  const [notifReady, setNotifReady] = useState(
    typeof Notification !== 'undefined' && Notification.permission === 'granted',
  )
  const itemsRef = useRef(items)
  const pollBusy = useRef(false)

  useEffect(() => {
    itemsRef.current = items
  }, [items])

  useEffect(() => {
    setItems(loadWatchlist(user?.id))
    setQuotes({})
    setToastAlerts([])
  }, [user?.id])

  const persist = useCallback(
    (next) => {
      setItems(next)
      itemsRef.current = next
      saveWatchlist(user?.id, next)
    },
    [user?.id],
  )

  const pushAlerts = useCallback((events) => {
    if (!events.length) return
    beep()
    setToastAlerts((prev) => [...events.map((e) => ({ ...e, id: `${Date.now()}-${e.kind}-${Math.random()}` })), ...prev].slice(0, 12))
    for (const event of events) {
      notifyBrowser('Stock Monitor', event.message)
    }
  }, [])

  const refreshQuotes = useCallback(async () => {
    const list = itemsRef.current
    if (!list.length || pollBusy.current) return
    pollBusy.current = true
    setRefreshing(true)
    setError('')
    const nextQuotes = {}
    const failures = []
    let nextItems = list
    let itemsChanged = false
    const alertEvents = []

    try {
      await Promise.all(
        list.map(async (item) => {
          try {
            const payload = await fetchLtp(item.exchange || 'NSE', item.tradingsymbol, item.token)
            const ltp = extractLtp(payload)
            if (ltp == null) throw new Error(payload?.message || 'LTP unavailable')
            nextQuotes[item.id] = ltp
            const fired = checkLevelAlerts(item, ltp)
            if (fired.length) {
              alertEvents.push(...fired)
              const alertPatch = { ...(item.alertsFired || {}) }
              for (const f of fired) alertPatch[f.kind] = true
              nextItems = nextItems.map((row) =>
                row.id === item.id ? { ...row, alertsFired: alertPatch } : row,
              )
              itemsChanged = true
            }
          } catch (err) {
            failures.push(`${item.display}: ${err?.response?.data?.detail || err.message || 'failed'}`)
          }
        }),
      )
      setQuotes((prev) => ({ ...prev, ...nextQuotes }))
      setLastRefreshed(new Date())
      if (itemsChanged) persist(nextItems)
      if (alertEvents.length) pushAlerts(alertEvents)
      if (failures.length) setError(failures.slice(0, 3).join(' · '))
    } finally {
      setRefreshing(false)
      pollBusy.current = false
    }
  }, [persist, pushAlerts])

  const itemIds = items.map((i) => i.id).join('|')
  useEffect(() => {
    if (!itemIds) return undefined
    refreshQuotes()
    const timer = setInterval(refreshQuotes, POLL_MS)
    return () => clearInterval(timer)
  }, [itemIds, refreshQuotes])

  const handleSelectSymbol = (hit) => {
    if (!hit?.token || !hit?.symbol) return
    setPending({
      tradingsymbol: hit.symbol,
      token: String(hit.token),
      exchange: hit.exchange || 'NSE',
      display: String(hit.symbol).replace(/-EQ$/i, ''),
      name: hit.name || '',
      buyBelow: '',
      stoploss: '',
      target: '',
      note: '',
    })
  }

  const handleAdd = () => {
    if (!pending?.token) return
    const id = `${pending.exchange}:${pending.tradingsymbol}`
    if (items.some((row) => row.id === id)) {
      setError(`${pending.display} is already on your monitor list`)
      return
    }
    const row = {
      id,
      display: pending.display,
      name: pending.name,
      tradingsymbol: pending.tradingsymbol,
      token: pending.token,
      exchange: pending.exchange || 'NSE',
      buyBelow: numOrNull(pending.buyBelow),
      stoploss: numOrNull(pending.stoploss),
      target: numOrNull(pending.target),
      note: String(pending.note || '').trim(),
      alertsFired: {},
      addedAt: new Date().toISOString(),
    }
    persist([row, ...items])
    setPending(null)
    setError('')
  }

  const updateItem = (id, patch) => {
    persist(
      items.map((row) => {
        if (row.id !== id) return row
        const next = { ...row, ...patch }
        // Re-arm alerts when levels change.
        if ('stoploss' in patch || 'target' in patch) {
          next.alertsFired = {
            ...(row.alertsFired || {}),
            ...('stoploss' in patch ? { stoploss: false } : {}),
            ...('target' in patch ? { target: false } : {}),
          }
        }
        return next
      }),
    )
  }

  const removeItem = (id) => {
    persist(items.filter((row) => row.id !== id))
    setQuotes((prev) => {
      const copy = { ...prev }
      delete copy[id]
      return copy
    })
  }

  const enableBrowserAlerts = async () => {
    if (typeof Notification === 'undefined') {
      setError('This browser does not support desktop notifications')
      return
    }
    const result = await Notification.requestPermission()
    setNotifReady(result === 'granted')
  }

  const dismissToast = (id) => setToastAlerts((prev) => prev.filter((a) => a.id !== id))

  const rows = useMemo(
    () =>
      items.map((item) => {
        const ltp = quotes[item.id] ?? null
        const verdict = evaluateBuyVerdict({
          ltp,
          buyBelow: item.buyBelow,
          stoploss: item.stoploss,
          target: item.target,
        })
        return { item, ltp, verdict }
      }),
    [items, quotes],
  )

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-cyan-400 text-xs uppercase tracking-widest">Watchlist</p>
          <h2 className="text-3xl font-bold mt-1">Stock Monitor</h2>
          <p className="text-slate-400 mt-1 max-w-2xl">
            Add NSE stocks, track live LTP, see a quick buy verdict, and get an alert when price hits your
            stoploss or target (while this page is open).
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!notifReady && (
            <button
              type="button"
              onClick={enableBrowserAlerts}
              className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 hover:border-slate-500"
            >
              Enable desktop alerts
            </button>
          )}
          <button
            type="button"
            onClick={refreshQuotes}
            disabled={refreshing || !items.length}
            className="rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-sm text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-40"
          >
            {refreshing ? 'Refreshing…' : 'Refresh prices'}
          </button>
        </div>
      </header>

      {toastAlerts.length > 0 && (
        <div className="space-y-2">
          {toastAlerts.map((alert) => (
            <div
              key={alert.id}
              className={`flex items-start justify-between gap-3 rounded-xl border px-4 py-3 text-sm ${
                alert.kind === 'stoploss'
                  ? 'border-rose-500/40 bg-rose-500/10 text-rose-100'
                  : 'border-emerald-500/40 bg-emerald-500/10 text-emerald-100'
              }`}
            >
              <p>
                <span className="font-semibold uppercase tracking-wide mr-2">
                  {alert.kind === 'stoploss' ? 'Stoploss' : 'Target'}
                </span>
                {alert.message}
              </p>
              <button type="button" className="text-xs opacity-70 hover:opacity-100" onClick={() => dismissToast(alert.id)}>
                Dismiss
              </button>
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
          {error}
        </div>
      )}

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 space-y-4">
        <h3 className="text-lg font-semibold text-slate-100">Add stock</h3>
        <div className="grid gap-4 md:grid-cols-[minmax(0,1.2fr)_repeat(3,minmax(0,0.7fr))]">
          <label className="block text-sm">
            <span className="text-slate-400">Symbol</span>
            <div className="mt-1">
              <SymbolLookupInput
                value={pending?.display || ''}
                onChange={() => {}}
                onSelect={handleSelectSymbol}
                placeholder="Search e.g. RELIANCE or TCS"
              />
            </div>
          </label>
          <label className="block text-sm">
            <span className="text-slate-400">Buy zone (optional)</span>
            <input
              type="number"
              step="0.05"
              value={pending?.buyBelow ?? ''}
              disabled={!pending}
              onChange={(e) => setPending((p) => (p ? { ...p, buyBelow: e.target.value } : p))}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5 disabled:opacity-40"
              placeholder="Buy below"
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-400">Stoploss</span>
            <input
              type="number"
              step="0.05"
              value={pending?.stoploss ?? ''}
              disabled={!pending}
              onChange={(e) => setPending((p) => (p ? { ...p, stoploss: e.target.value } : p))}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5 disabled:opacity-40"
              placeholder="Alert if ≤"
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-400">Target</span>
            <input
              type="number"
              step="0.05"
              value={pending?.target ?? ''}
              disabled={!pending}
              onChange={(e) => setPending((p) => (p ? { ...p, target: e.target.value } : p))}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5 disabled:opacity-40"
              placeholder="Alert if ≥"
            />
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={handleAdd}
            disabled={!pending}
            className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-40"
          >
            Add to monitor
          </button>
          {pending && (
            <p className="text-xs text-slate-500">
              Selected {pending.display}
              {pending.name ? ` · ${pending.name}` : ''} · token {pending.token}
            </p>
          )}
          {lastRefreshed && (
            <p className="text-xs text-slate-500 ml-auto">
              Last price update {lastRefreshed.toLocaleTimeString('en-IN', { hour12: false })}
            </p>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-950/80 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Stock</th>
                <th className="px-4 py-3 font-medium">LTP</th>
                <th className="px-4 py-3 font-medium">Verdict</th>
                <th className="px-4 py-3 font-medium">Buy zone</th>
                <th className="px-4 py-3 font-medium">Stoploss</th>
                <th className="px-4 py-3 font-medium">Target</th>
                <th className="px-4 py-3 font-medium">Note</th>
                <th className="px-4 py-3 font-medium" />
              </tr>
            </thead>
            <tbody>
              {!rows.length && (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-slate-500">
                    No stocks yet — search and add one above. List is saved in this browser for your account.
                  </td>
                </tr>
              )}
              {rows.map(({ item, ltp, verdict }) => (
                <tr key={item.id} className="border-t border-slate-800/80 align-top">
                  <td className="px-4 py-3">
                    <p className="font-semibold text-slate-100">{item.display}</p>
                    <p className="text-xs text-slate-500">{item.name || item.tradingsymbol}</p>
                  </td>
                  <td className="px-4 py-3 font-mono text-base text-slate-100">{formatInr(ltp)}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-semibold ${toneClass(verdict.tone)}`}>
                      {verdict.label}
                    </span>
                    <p className="mt-1 text-xs text-slate-500 max-w-[14rem]">{verdict.detail}</p>
                  </td>
                  <td className="px-4 py-3">
                    <input
                      type="number"
                      step="0.05"
                      value={item.buyBelow ?? ''}
                      onChange={(e) => updateItem(item.id, { buyBelow: numOrNull(e.target.value) })}
                      className="w-28 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <input
                      type="number"
                      step="0.05"
                      value={item.stoploss ?? ''}
                      onChange={(e) => updateItem(item.id, { stoploss: numOrNull(e.target.value) })}
                      className="w-28 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5"
                    />
                    {item.alertsFired?.stoploss && (
                      <p className="mt-1 text-[10px] uppercase tracking-wide text-rose-400">Alerted</p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <input
                      type="number"
                      step="0.05"
                      value={item.target ?? ''}
                      onChange={(e) => updateItem(item.id, { target: numOrNull(e.target.value) })}
                      className="w-28 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5"
                    />
                    {item.alertsFired?.target && (
                      <p className="mt-1 text-[10px] uppercase tracking-wide text-emerald-400">Alerted</p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <input
                      type="text"
                      value={item.note || ''}
                      onChange={(e) => updateItem(item.id, { note: e.target.value })}
                      className="w-36 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5"
                      placeholder="Optional"
                    />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => removeItem(item.id)}
                      className="text-xs text-slate-500 hover:text-rose-300"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <p className="text-xs text-slate-600">
        Alerts fire in this tab every ~10s while prices refresh. Connect Angel One on Account if LTP fails.
        Changing SL/target re-arms that alert.
      </p>
    </div>
  )
}
