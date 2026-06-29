import { useEffect, useRef, useState } from 'react'
import { fetchLatestScan, fetchOptionChain, fetchStreamStatus } from '../api'

function wsBase() {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${protocol}://${window.location.host}/api/v1/market/ws`
}

export default function MarketLivePanel({ compact = false }) {
  const [streamStatus, setStreamStatus] = useState(null)
  const [scan, setScan] = useState(null)
  const [optionChain, setOptionChain] = useState(null)
  const [ticks, setTicks] = useState([])
  const wsRef = useRef(null)

  useEffect(() => {
    fetchStreamStatus().then(setStreamStatus).catch(() => null)
    fetchLatestScan().then(setScan).catch(() => null)
    fetchOptionChain('NIFTY').then(setOptionChain).catch(() => null)

    const ws = new WebSocket(wsBase())
    wsRef.current = ws
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data)
        if (payload.token && payload.ltp) {
          setTicks((prev) => [payload, ...prev.filter((t) => t.token !== payload.token)].slice(0, 12))
        }
        if (payload.hits) {
          setScan(payload)
        }
        if (payload.underlying && payload.rows) {
          setOptionChain(payload)
        }
      } catch {
        // ignore malformed frames
      }
    }
    return () => ws.close()
  }, [])

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-emerald-400 text-xs uppercase tracking-widest">Phase 2</p>
          <h2 className="text-xl font-semibold">Live Market Engine</h2>
        </div>
        <span className={`text-xs px-2 py-1 rounded ${streamStatus?.connected ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'}`}>
          {streamStatus?.connected ? 'Streaming' : 'Offline'}
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-3 mb-4 text-sm">
        <Metric label="Subscriptions" value={streamStatus?.subscriptions ?? 0} />
        <Metric label="Ticks Received" value={streamStatus?.ticks_received ?? 0} />
        <Metric label="Scanner" value={streamStatus?.scanner_running ? 'Running' : 'Stopped'} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="font-medium mb-2">Live Ticks</h3>
          <div className="space-y-2 max-h-64 overflow-auto">
            {ticks.length === 0 && <p className="text-slate-500 text-sm">Waiting for tick stream...</p>}
            {ticks.map((tick) => (
              <div key={tick.token} className="flex justify-between border-b border-slate-800 pb-1">
                <span>{tick.symbol || tick.token}</span>
                <span className="font-mono">₹{Number(tick.ltp).toFixed(2)}</span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <h3 className="font-medium mb-2">Scanner Hits</h3>
          <div className="space-y-2 max-h-64 overflow-auto">
            {(scan?.hits || []).slice(0, 8).map((hit) => (
              <div key={`${hit.scan_type}-${hit.symbol}`} className="flex justify-between text-sm border-b border-slate-800 pb-1">
                <span>{hit.symbol} · {hit.scan_type}</span>
                <span className="text-emerald-300">{hit.score.toFixed(0)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {optionChain && !compact && (
        <div className="mt-4 pt-4 border-t border-slate-800">
          <div className="flex justify-between text-sm mb-2">
            <span>NIFTY Option Chain PCR</span>
            <span className="font-mono">{optionChain.pcr ?? '—'}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span>CE OI / PE OI</span>
            <span className="font-mono">{optionChain.total_ce_oi} / {optionChain.total_pe_oi}</span>
          </div>
        </div>
      )}
    </section>
  )
}

function Metric({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-800 p-3">
      <p className="text-slate-500 text-xs uppercase">{label}</p>
      <p className="text-lg font-semibold mt-1">{value}</p>
    </div>
  )
}
