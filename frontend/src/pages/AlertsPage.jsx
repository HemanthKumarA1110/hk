import { useEffect, useState } from 'react'
import { fetchAlertsStatus } from '../api'

export default function AlertsPage() {
  const [status, setStatus] = useState(null)

  useEffect(() => {
    fetchAlertsStatus().then(setStatus).catch(() => null)
  }, [])

  return (
    <div>
      <header className="mb-6">
        <p className="text-yellow-400 text-xs uppercase tracking-widest">Alerts</p>
        <h2 className="text-3xl font-bold mt-1">Signal & Price Alerts</h2>
        <p className="text-slate-400 mt-1">Real-time notifications for entries, exits, and risk events</p>
      </header>

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-6">
        <p className="text-slate-400 text-sm mb-4">
          Alert engine is wired to the platform gateway. Full rule builder and push notifications ship in Phase 6.
        </p>
        <div className="rounded-lg bg-slate-950/50 p-4 font-mono text-xs text-slate-500">
          Service status: {status?.status || 'unknown'} · Phase {status?.phase ?? 6}
        </div>
      </section>
    </div>
  )
}
