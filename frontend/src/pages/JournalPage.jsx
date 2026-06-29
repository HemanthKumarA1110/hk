import { useEffect, useState } from 'react'
import { fetchAdminJournal, fetchJournalInsights } from '../api'

export default function JournalPage() {
  const [entries, setEntries] = useState([])
  const [insights, setInsights] = useState(null)

  useEffect(() => {
    fetchAdminJournal().then((d) => setEntries(d.entries || [])).catch(() => null)
    fetchJournalInsights().then(setInsights).catch(() => null)
  }, [])

  return (
    <div>
      <header className="mb-6">
        <p className="text-pink-400 text-xs uppercase tracking-widest">Trade Journal</p>
        <h2 className="text-3xl font-bold mt-1">Performance Log</h2>
        <p className="text-slate-400 mt-1">Closed trades feed adaptive AI learning</p>
      </header>

      {insights && (
        <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 mb-6">
          <h3 className="font-semibold mb-2">Insights</h3>
          <ul className="text-sm text-slate-400 space-y-1">
            {(insights.insights || []).map((line) => (
              <li key={line}>• {line}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-950/50 text-slate-500 text-xs uppercase">
            <tr>
              <th className="text-left p-3">Symbol</th>
              <th className="text-left p-3">Engine</th>
              <th className="text-left p-3">Side</th>
              <th className="text-right p-3">P&L</th>
              <th className="text-right p-3">AI Score</th>
              <th className="text-left p-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id} className="border-t border-slate-800">
                <td className="p-3 font-medium">{e.symbol}</td>
                <td className="p-3 text-slate-400">{e.engine}</td>
                <td className="p-3">{e.side}</td>
                <td className={`p-3 text-right font-mono ${(e.pnl || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  ₹{Number(e.pnl || 0).toLocaleString('en-IN')}
                </td>
                <td className="p-3 text-right">{e.ai_score ?? '—'}</td>
                <td className="p-3 text-slate-400">{e.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}
